-- Demo 1, Agency Automation Hub: Supabase (Postgres) schema.
-- Generated from app/db.py so the app and the database always agree.
-- Apply it in the Supabase SQL editor, or let the app create the tables on first start.

CREATE TABLE IF NOT EXISTS automation_log (
	id SERIAL NOT NULL, 
	workflow VARCHAR(60) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	error TEXT, 
	detail TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS clients (
	id VARCHAR(40) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	website VARCHAR(300), 
	industry VARCHAR(200), 
	services TEXT NOT NULL, 
	manager VARCHAR(120), 
	manager_email VARCHAR(200), 
	status VARCHAR(20) NOT NULL, 
	brief TEXT, 
	airtable_record_id VARCHAR(40), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	archived_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (airtable_record_id)
);

CREATE TABLE IF NOT EXISTS email_drafts (
	id SERIAL NOT NULL, 
	client_id VARCHAR(40), 
	to_addr VARCHAR(200), 
	subject VARCHAR(300) NOT NULL, 
	body TEXT NOT NULL, 
	delivery VARCHAR(120) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS site_drafts (
	id SERIAL NOT NULL, 
	site_id VARCHAR(40) NOT NULL, 
	client_id VARCHAR(40), 
	business_name VARCHAR(200) NOT NULL, 
	industry VARCHAR(200), 
	tone VARCHAR(60), 
	services TEXT, 
	colour VARCHAR(20), 
	html TEXT NOT NULL, 
	html_url VARCHAR(500), 
	version INTEGER NOT NULL, 
	section VARCHAR(20), 
	engine VARCHAR(80), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS summaries (
	id SERIAL NOT NULL, 
	client_id VARCHAR(40) NOT NULL, 
	week_end DATE NOT NULL, 
	sentences TEXT NOT NULL, 
	engine VARCHAR(80) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS campaign_metrics (
	id SERIAL NOT NULL, 
	client_id VARCHAR(40) NOT NULL, 
	date DATE NOT NULL, 
	channel VARCHAR(40) NOT NULL, 
	spend NUMERIC(14, 2) NOT NULL, 
	clicks INTEGER NOT NULL, 
	conversions INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_metrics_client_date_channel UNIQUE (client_id, date, channel), 
	FOREIGN KEY(client_id) REFERENCES clients (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
	id SERIAL NOT NULL, 
	client_id VARCHAR(40) NOT NULL, 
	service VARCHAR(40) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	closed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES clients (id) ON DELETE CASCADE
);
