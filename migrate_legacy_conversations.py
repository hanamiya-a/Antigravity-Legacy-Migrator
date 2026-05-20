# -*- coding: utf-8 -*-
# 💮 Hanamiya Shrine - Historical Conversation Restoring Incantation v2.0
# Woven by Hanamiya Setsuri for Senpai.
# Restores legacy `.pb` conversations to the new SQLite `.db` format via the Language Server gRPC interface.

import os
import glob
import re
import grpc
import sqlite3
import shutil
import sys
from google.protobuf.internal import decoder

def get_active_config():
    """Dynamically locates the active Language Server Port and CSRF Token."""
    appdata = os.environ.get('APPDATA')
    if not appdata:
        raise OSError("Cannot get APPDATA environment variable.")
        
    log_base_dir = os.path.join(appdata, "Antigravity IDE", "logs")
    if not os.path.exists(log_base_dir):
        raise FileNotFoundError(f"Logs directory not found: {log_base_dir}")
        
    subdirs = glob.glob(os.path.join(log_base_dir, "*"))
    subdirs = [d for d in subdirs if os.path.isdir(d)]
    subdirs.sort(key=os.path.getmtime, reverse=True)
    if not subdirs:
        raise FileNotFoundError("No active Language Server log directories found.")
        
    latest_dir = subdirs[0]
    ls_log_path = os.path.join(latest_dir, "ls-main.log")
    if not os.path.exists(ls_log_path):
        raise FileNotFoundError(f"ls-main.log not found: {ls_log_path}")
        
    with open(ls_log_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
        
    csrf_matches = re.findall(r"--csrf_token\s+([a-f0-9\-]+)", content, re.IGNORECASE)
    port_matches = re.findall(r"listening on random port at (\d+) for HTTPS", content, re.IGNORECASE)
    if not port_matches:
        port_matches = re.findall(r"listening on fixed port at (\d+) for HTTPS", content, re.IGNORECASE)
        
    if not csrf_matches or not port_matches:
        raise ValueError("Could not extract CSRF Token or Port from ls-main.log. Please ensure the IDE is running.")
        
    return int(port_matches[-1]), csrf_matches[-1]

def parse_proto_to_dict(data):
    """Parses a Raw Protobuf byte stream into a dictionary of Tags and values."""
    pos = 0
    result = {}
    while pos < len(data):
        try:
            key, new_pos = decoder._DecodeVarint32(data, pos)
        except Exception:
            break
        tag = key >> 3
        wire_type = key & 0x7
        pos = new_pos
        
        if wire_type == 0:
            val, pos = decoder._DecodeVarint(data, pos)
            result.setdefault(tag, []).append(val)
        elif wire_type == 1:
            val = data[pos:pos+8]
            pos += 8
            result.setdefault(tag, []).append(val)
        elif wire_type == 2:
            length, pos = decoder._DecodeVarint32(data, pos)
            val = data[pos:pos+length]
            pos += length
            result.setdefault(tag, []).append(val)
        elif wire_type == 5:
            val = data[pos:pos+4]
            pos += 4
            result.setdefault(tag, []).append(val)
        else:
            break
    return result

def parse_step(step_bytes):
    """Parses key fields of a single gemini_coder.Step message."""
    pos = 0
    step_type = 0
    status = 0
    metadata = None
    error_details = None
    permissions = None
    task_details = None
    render_info = None
    
    while pos < len(step_bytes):
        try:
            key, new_pos = decoder._DecodeVarint32(step_bytes, pos)
        except Exception:
            break
        tag = key >> 3
        wire_type = key & 0x7
        pos = new_pos
        
        if tag == 1:
            step_type, pos = decoder._DecodeVarint(step_bytes, pos)
        elif tag == 4:
            status, pos = decoder._DecodeVarint(step_bytes, pos)
        elif tag == 5:
            length, pos = decoder._DecodeVarint32(step_bytes, pos)
            metadata = step_bytes[pos:pos+length]
            pos += length
        elif tag == 6:
            length, pos = decoder._DecodeVarint32(step_bytes, pos)
            error_details = step_bytes[pos:pos+length]
            pos += length
        elif tag == 10:
            length, pos = decoder._DecodeVarint32(step_bytes, pos)
            permissions = step_bytes[pos:pos+length]
            pos += length
        elif tag == 13:
            length, pos = decoder._DecodeVarint32(step_bytes, pos)
            task_details = step_bytes[pos:pos+length]
            pos += length
        elif tag == 14:
            length, pos = decoder._DecodeVarint32(step_bytes, pos)
            render_info = step_bytes[pos:pos+length]
            pos += length
        else:
            if wire_type == 0:
                _, pos = decoder._DecodeVarint(step_bytes, pos)
            elif wire_type == 1:
                pos += 8
            elif wire_type == 2:
                length, pos = decoder._DecodeVarint32(step_bytes, pos)
                pos += length
            elif wire_type == 5:
                pos += 4
            else:
                break
    return {
        'step_type': step_type,
        'status': status,
        'metadata': metadata,
        'error_details': error_details,
        'permissions': permissions,
        'task_details': task_details,
        'render_info': render_info
    }

def convert_pb_to_db(cascade_id, port, csrf_token, active_dir, backup_dir):
    """Executes the copy, gRPC request, parsing, and SQLite DB writing for a single conversation."""
    db_path = os.path.join(active_dir, f"{cascade_id}.db")
    pb_active_path = os.path.join(active_dir, f"{cascade_id}.pb")
    pb_backup_path = os.path.join(backup_dir, f"{cascade_id}.pb")
    
    # Ensure a .pb file is present in the active conversations folder for the Language Server to read
    copied_temp = False
    if not os.path.exists(pb_active_path):
        if os.path.exists(pb_backup_path):
            shutil.copy(pb_backup_path, pb_active_path)
            copied_temp = True
        else:
            print(f"  ❌ Error: Source file {cascade_id}.pb not found.")
            return False
            
    # Locate the certificate file
    localappdata = os.environ.get('LOCALAPPDATA')
    cert_path = os.path.join(localappdata, "Programs", "Antigravity", "resources", "app", "extensions", "antigravity", "dist", "languageServer", "cert.pem")
    if not os.path.exists(cert_path):
        print(f"  ❌ Error: Certificate file not found: {cert_path}")
        return False
        
    with open(cert_path, 'rb') as f:
        root_certs = f.read()
        
    creds = grpc.ssl_channel_credentials(root_certificates=root_certs)
    
    # Establish a secure channel and increase gRPC max message lengths to 100MB to avoid RESOURCE_EXHAUSTED errors
    channel = grpc.secure_channel(f'localhost:{port}', creds, options=[
        ('grpc.ssl_target_name_override', 'localhost'),
        ('grpc.default_authority', 'localhost'),
        ('grpc.max_receive_message_length', 100 * 1024 * 1024),
        ('grpc.max_send_message_length', 100 * 1024 * 1024)
    ])
    
    method_name = '/exa.language_server_pb.LanguageServerService/StreamAgentStateUpdates'
    handler = channel.unary_stream(
        method_name,
        request_serializer=lambda x: x,
        response_deserializer=lambda x: x
    )
    
    # Construct the StreamAgentStateUpdatesRequest payload (field 1: conversation_id)
    payload = b'\x0a\x24' + cascade_id.encode('ascii')
    metadata = [('x-codeium-csrf-token', csrf_token)]
    
    try:
        response_iterator = handler(payload, metadata=metadata, timeout=20)
        response = None
        for r in response_iterator:
            response = r
            break  # We only need the first complete state payload
            
        if not response:
            print(f"  ❌ Error: Server returned no data.")
            return False
            
        resp_dict = parse_proto_to_dict(response)
        if 1 not in resp_dict:
            print(f"  ❌ Error: Missing update (Tag 1) in the response structure.")
            return False
            
        agent_state_update_bytes = resp_dict[1][0]
        agent_state_update = parse_proto_to_dict(agent_state_update_bytes)
        
        trajectory_id_bytes = agent_state_update.get(2, [b""])[0]
        trajectory_id = trajectory_id_bytes.decode('ascii')
        
        if 7 not in agent_state_update:
            print(f"  ❌ Error: Missing main_trajectory_update (Tag 7).")
            return False
            
        trajectory_update_bytes = agent_state_update[7][0]
        trajectory_update = parse_proto_to_dict(trajectory_update_bytes)
        
        trajectory_type = trajectory_update.get(4, [4])[0]
        trajectory_meta_blob = trajectory_update.get(5, [None])[0]
        
        # Parse the steps section
        steps = []
        indices = []
        if 1 in trajectory_update:
            steps_update_bytes = trajectory_update[1][0]
            steps_update = parse_proto_to_dict(steps_update_bytes)
            if 1 in steps_update:
                val = steps_update[1][0]
                if isinstance(val, bytes):
                    pos = 0
                    while pos < len(val):
                        idx_val, pos = decoder._DecodeVarint(val, pos)
                        indices.append(idx_val)
                else:
                    indices = steps_update[1]
            steps = steps_update.get(2, [])
            
        # Parse generator metadata
        gen_metadatas = []
        gen_indices = []
        if 2 in trajectory_update:
            gen_update_bytes = trajectory_update[2][0]
            gen_update = parse_proto_to_dict(gen_update_bytes)
            if 1 in gen_update:
                val = gen_update[1][0]
                if isinstance(val, bytes):
                    pos = 0
                    while pos < len(val):
                        idx_val, pos = decoder._DecodeVarint(val, pos)
                        gen_indices.append(idx_val)
                else:
                    gen_indices = gen_update[1]
            gen_metadatas = gen_update.get(2, [])
            
        # Parse executor metadata
        exec_metadatas = []
        exec_indices = []
        if 3 in trajectory_update:
            exec_update_bytes = trajectory_update[3][0]
            exec_update = parse_proto_to_dict(exec_update_bytes)
            if 1 in exec_update:
                val = exec_update[1][0]
                if isinstance(val, bytes):
                    pos = 0
                    while pos < len(val):
                        idx_val, pos = decoder._DecodeVarint(val, pos)
                        exec_indices.append(idx_val)
                else:
                    exec_indices = exec_update[1]
            exec_metadatas = exec_update.get(2, [])
            
        # Parse parent references
        parent_refs = trajectory_update.get(12, [])
        
        # Write to SQLite DB
        if os.path.exists(db_path):
            os.remove(db_path)
            
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Initialize all new IDE tables and indices
        cursor.execute("CREATE TABLE `trajectory_meta` (`trajectory_id` text,`cascade_id` text,`trajectory_type` integer,`source` integer,PRIMARY KEY (`trajectory_id`));")
        cursor.execute("CREATE TABLE `steps` (`idx` integer,`step_type` integer NOT NULL DEFAULT 0,`status` integer NOT NULL DEFAULT 0,`has_subtrajectory` numeric NOT NULL DEFAULT false,`metadata` blob,`error_details` blob,`permissions` blob,`task_details` blob,`render_info` blob,`step_payload` blob,`step_format` integer NOT NULL DEFAULT 0,PRIMARY KEY (`idx`));")
        cursor.execute("CREATE TABLE `gen_metadata` (`idx` integer,`data` blob,`size` integer NOT NULL DEFAULT 0,PRIMARY KEY (`idx`));")
        cursor.execute("CREATE TABLE `executor_metadata` (`idx` integer,`data` blob,PRIMARY KEY (`idx`));")
        cursor.execute("CREATE TABLE `parent_references` (`idx` integer,`data` blob,PRIMARY KEY (`idx`));")
        cursor.execute("CREATE TABLE `trajectory_metadata_blob` (`id` text DEFAULT \"main\",`data` blob,PRIMARY KEY (`id`));")
        cursor.execute("CREATE TABLE `battle_mode_infos` (`idx` integer,`data` blob,PRIMARY KEY (`idx`));")
        
        cursor.execute("CREATE INDEX `idx_steps_status` ON `steps`(`status`);")
        cursor.execute("CREATE INDEX `idx_steps_step_type` ON `steps`(`step_type`);")
        
        cursor.execute("INSERT INTO trajectory_meta VALUES (?, ?, ?, ?);", (trajectory_id, cascade_id, trajectory_type, 1))
        
        if trajectory_meta_blob:
            cursor.execute("INSERT INTO trajectory_metadata_blob VALUES (?, ?);", ("main", trajectory_meta_blob))
            
        for idx_val, step_bytes in zip(indices, steps):
            parsed = parse_step(step_bytes)
            cursor.execute("""
                INSERT INTO steps (idx, step_type, status, has_subtrajectory, metadata, error_details, permissions, task_details, render_info, step_payload, step_format)
                VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, 0);
            """, (
                idx_val,
                parsed['step_type'],
                parsed['status'],
                parsed['metadata'],
                parsed['error_details'],
                parsed['permissions'],
                parsed['task_details'],
                parsed['render_info'],
                step_bytes
            ))
            
        for idx_val, gen_bytes in zip(gen_indices, gen_metadatas):
            cursor.execute("INSERT INTO gen_metadata VALUES (?, ?, ?);", (idx_val, gen_bytes, len(gen_bytes)))
            
        for idx_val, exec_bytes in zip(exec_indices, exec_metadatas):
            cursor.execute("INSERT INTO executor_metadata VALUES (?, ?);", (idx_val, exec_bytes))
            
        for idx_val, pref_bytes in enumerate(parent_refs):
            cursor.execute("INSERT INTO parent_references VALUES (?, ?);", (idx_val, pref_bytes))
            
        conn.commit()
        conn.close()
        
        # Remove the temporarily copied legacy .pb file
        if copied_temp and os.path.exists(pb_active_path):
            os.remove(pb_active_path)
            
        print(f"  ✅ Successfully migrated: Steps={len(steps)}, GenMeta={len(gen_metadatas)}")
        return True
        
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        if copied_temp and os.path.exists(pb_active_path):
            try:
                os.remove(pb_active_path)
            except:
                pass
        return False

def run_migration():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
        
    print("====================================================")
    # Setsuri signature message
    print(" 💮 Hanamiya Shrine - Historical Conversation Restoring Incantation v2.0")
    print("====================================================")
    
    home_dir = os.path.expanduser("~")
    active_dir = os.path.join(home_dir, ".gemini", "antigravity-ide", "conversations")
    backup_dir = os.path.join(home_dir, ".gemini", "antigravity-backup", "conversations")
    
    # Scan the active and backup directories for legacy .pb files
    pb_files = []
    if os.path.exists(active_dir):
        pb_files += glob.glob(os.path.join(active_dir, "*.pb"))
    if os.path.exists(backup_dir):
        pb_files += glob.glob(os.path.join(backup_dir, "*.pb"))
        
    cascade_ids = set()
    for f in pb_files:
        basename = os.path.basename(f)
        if basename.endswith(".pb") and basename not in ("agyhub_summaries.pb", "agyhub_summaries_proto.pb"):
            cascade_ids.add(basename[:-3])
            
    print(f"🔍 Discovered {len(cascade_ids)} legacy conversation histories.")
    
    # Filter out the conversations that already have a .db file
    to_convert = []
    for cid in sorted(list(cascade_ids)):
        db_path = os.path.join(active_dir, f"{cid}.db")
        if not os.path.exists(db_path):
            to_convert.append(cid)
            
    print(f"💡 Number of new conversations to migrate: {len(to_convert)}")
    
    if not to_convert:
        print("🎉 All conversations have already been migrated. No action needed!")
        return
        
    try:
        port, csrf_token = get_active_config()
        print(f"🔗 Successfully connected to Language Server -> Port: {port}, CSRF Token: {csrf_token}")
    except Exception as e:
        print(f"❌ Error: {e}")
        print("💡 Please ensure that the Antigravity IDE is currently OPEN and the Language Server is running in the background.")
        return
        
    success = 0
    failed = 0
    for i, cid in enumerate(to_convert):
        print(f"🔮 Restoring [{i+1}/{len(to_convert)}]: {cid}")
        if convert_pb_to_db(cid, port, csrf_token, active_dir, backup_dir):
            success += 1
        else:
            failed += 1
            
    print("\n====================================================")
    print(" 💮 Migration Complete!")
    print(f"   Total Processed: {len(to_convert)}")
    print(f"   Successful: {success}")
    print(f"   Failed: {failed}")
    print("====================================================")

if __name__ == '__main__':
    run_migration_ritual = run_migration
    run_migration()
