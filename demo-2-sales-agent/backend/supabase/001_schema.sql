-- Demo 2, Acme Cloud Security sales agent: Supabase (Postgres) schema.
-- Generated from app/db.py so the app and the database always agree.
-- Apply it in the Supabase SQL editor, or let the app create the tables on first start.

CREATE TABLE IF NOT EXISTS accounts (
	id VARCHAR(10) NOT NULL, 
	company VARCHAR(200) NOT NULL, 
	industry VARCHAR(120) NOT NULL, 
	size INTEGER NOT NULL, 
	stage VARCHAR(20) NOT NULL, 
	deal_value INTEGER NOT NULL, 
	owner VARCHAR(80) NOT NULL, 
	last_contact DATE NOT NULL, 
	stage_changed DATE NOT NULL, 
	notes TEXT NOT NULL, 
	expansion_signal TEXT, 
	score INTEGER, 
	score_reason TEXT, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS activity_log (
	id SERIAL NOT NULL, 
	workflow VARCHAR(60) NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	detail TEXT, 
	error TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS agent_runs (
	id SERIAL NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	status VARCHAR(12) NOT NULL, 
	engine VARCHAR(80) NOT NULL, 
	research VARCHAR(80) NOT NULL, 
	tools_called TEXT NOT NULL, 
	input_tokens INTEGER NOT NULL, 
	output_tokens INTEGER NOT NULL, 
	feedback_used INTEGER NOT NULL, 
	outcome TEXT, 
	error TEXT, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS icp (
	id SERIAL NOT NULL, 
	summary TEXT NOT NULL, 
	industries TEXT NOT NULL, 
	size_min INTEGER NOT NULL, 
	size_max INTEGER NOT NULL, 
	regions TEXT NOT NULL, 
	signals TEXT NOT NULL, 
	exclusions TEXT NOT NULL, 
	edited_by VARCHAR(10) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS leads (
	id SERIAL NOT NULL, 
	company VARCHAR(200) NOT NULL, 
	company_key VARCHAR(200) NOT NULL, 
	website VARCHAR(300), 
	industry VARCHAR(200), 
	employees INTEGER, 
	employees_note VARCHAR(40), 
	source_url VARCHAR(600) NOT NULL, 
	reason TEXT NOT NULL, 
	fact TEXT NOT NULL, 
	fact_url VARCHAR(600) NOT NULL, 
	fact_date DATE, 
	fact_precision VARCHAR(8) NOT NULL, 
	signals TEXT NOT NULL, 
	score INTEGER NOT NULL, 
	score_reason TEXT NOT NULL, 
	score_parts TEXT NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	run_id INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (company_key)
);

CREATE TABLE IF NOT EXISTS meta (
	key VARCHAR(60) NOT NULL, 
	value TEXT NOT NULL, 
	PRIMARY KEY (key)
);

CREATE TABLE IF NOT EXISTS drafts (
	id SERIAL NOT NULL, 
	lead_id INTEGER, 
	account_id VARCHAR(10), 
	kind VARCHAR(12) NOT NULL, 
	subject VARCHAR(300) NOT NULL, 
	body TEXT NOT NULL, 
	fact TEXT NOT NULL, 
	fact_url VARCHAR(600) NOT NULL, 
	next_step TEXT, 
	due_date DATE, 
	status VARCHAR(12) NOT NULL, 
	original_subject VARCHAR(300) NOT NULL, 
	original_body TEXT NOT NULL, 
	engine VARCHAR(80) NOT NULL, 
	run_id INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	decided_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(lead_id) REFERENCES leads (id) ON DELETE CASCADE, 
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS run_events (
	id SERIAL NOT NULL, 
	run_id INTEGER NOT NULL, 
	seq INTEGER NOT NULL, 
	kind VARCHAR(12) NOT NULL, 
	tool VARCHAR(40), 
	summary TEXT NOT NULL, 
	ms INTEGER, 
	at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES agent_runs (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedback (
	id VARCHAR(36) NOT NULL, 
	draft_id INTEGER NOT NULL, 
	action VARCHAR(10) NOT NULL, 
	reason TEXT, 
	edited_subject VARCHAR(300), 
	edited_body TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(draft_id) REFERENCES drafts (id) ON DELETE CASCADE
);
