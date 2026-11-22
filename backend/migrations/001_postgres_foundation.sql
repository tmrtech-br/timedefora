-- PostgreSQL production-oriented foundation; requires a production migration runner.
-- Not applied by the SQLite demo API.
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE TABLE IF NOT EXISTS games(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),title text NOT NULL, platform text NOT NULL, commercial_rights_verified boolean NOT NULL DEFAULT false);
CREATE TABLE IF NOT EXISTS consoles(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),name text NOT NULL, platform text NOT NULL, status text NOT NULL DEFAULT 'unconfigured');
CREATE TABLE IF NOT EXISTS console_agents(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),host_name text NOT NULL, last_heartbeat timestamptz);
CREATE TABLE IF NOT EXISTS capture_devices(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),agent_id uuid REFERENCES console_agents(id),device_identifier text NOT NULL,UNIQUE(agent_id,device_identifier));
CREATE TABLE IF NOT EXISTS control_adapters(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),console_id uuid REFERENCES consoles(id),adapter_type text NOT NULL,valid boolean DEFAULT false);
CREATE TABLE IF NOT EXISTS console_connection_configs(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),console_id uuid NOT NULL UNIQUE REFERENCES consoles(id),agent_id uuid REFERENCES console_agents(id),adapter_kind text NOT NULL CHECK(adapter_kind IN ('simulated','chiaki_web_remote_play','native_remote_play','hdmi_capture','unconfigured')),capture_device_id uuid REFERENCES capture_devices(id),control_adapter_id uuid REFERENCES control_adapters(id),is_validated boolean NOT NULL DEFAULT false,updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS remote_play_pairings(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),console_id uuid UNIQUE REFERENCES consoles(id),secret_reference text NOT NULL,paired_at timestamptz);
CREATE TABLE IF NOT EXISTS console_connection_health(console_id uuid PRIMARY KEY REFERENCES consoles(id),checked_at timestamptz, fps real,rtt_ms real,jitter_ms real,bitrate_kbps real,frames_dropped integer,status text);
CREATE TABLE IF NOT EXISTS console_game_assignments(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),console_id uuid NOT NULL REFERENCES consoles(id),game_id uuid NOT NULL REFERENCES games(id),window tstzrange NOT NULL,status text NOT NULL DEFAULT 'active', EXCLUDE USING gist(console_id WITH =,window WITH &&) WHERE(status='active'));
CREATE TABLE IF NOT EXISTS reservations(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),assignment_id uuid NOT NULL REFERENCES console_game_assignments(id),public_name text NOT NULL,window tstzrange NOT NULL,status text NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS audit_logs(id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,actor_id uuid,action text NOT NULL,entity_type text NOT NULL,entity_id uuid,created_at timestamptz DEFAULT now(),details jsonb NOT NULL DEFAULT '{}'::jsonb);
-- Reservations also require exclusion at the CONSOLE level, across all assignments.
-- Implement a console_id denormalization, transactional guard and status-filtered exclusion
-- when building the production booking engine. RLS/auth/payment tables are pending phases.
