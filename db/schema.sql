PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL,
    company TEXT NOT NULL,
    verification_status TEXT NOT NULL DEFAULT 'verified'
        CHECK (verification_status IN ('pending', 'verified', 'rejected')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS engineers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    service_area TEXT NOT NULL,
    current_workload INTEGER NOT NULL DEFAULT 0 CHECK (current_workload >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS engineer_skills (
    engineer_id TEXT NOT NULL,
    skill TEXT NOT NULL CHECK (
        skill IN ('technician', 'plumber', 'HVAC', 'electrical', 'sanitary')
    ),
    PRIMARY KEY (engineer_id, skill),
    FOREIGN KEY (engineer_id) REFERENCES engineers (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'pending',
            'scheduled',
            'in_progress',
            'completed',
            'cancelled',
            'locked'
        )
    ),
    priority TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    assigned_engineer_id TEXT,
    service_area TEXT,
    required_skill TEXT CHECK (
        required_skill IS NULL OR required_skill IN (
            'technician',
            'plumber',
            'HVAC',
            'electrical',
            'sanitary'
        )
    ),
    scheduled_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_engineer_id) REFERENCES engineers (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    amount NUMERIC NOT NULL CHECK (amount >= 0),
    subtotal NUMERIC NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    tax NUMERIC NOT NULL DEFAULT 0 CHECK (tax >= 0),
    total NUMERIC NOT NULL DEFAULT 0 CHECK (total >= 0),
    status TEXT NOT NULL CHECK (
        status IN ('draft', 'issued', 'paid', 'void', 'unpaid', 'overdue', 'cancelled')
    ),
    due_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    priority TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    confidence REAL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    needs_escalation INTEGER CHECK (needs_escalation IN (0, 1)),
    assigned_engineer_id TEXT,
    job_id TEXT,
    escalation_reason TEXT,
    status TEXT NOT NULL CHECK (
        status IN (
            'open',
            'in_progress',
            'waiting_for_customer',
            'waiting_for_engineer',
            'resolved',
            'escalated',
            'closed',
            'processed'
        )
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_engineer_id) REFERENCES engineers (id) ON DELETE SET NULL,
    FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS ticket_messages (
    id TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    sender_type TEXT NOT NULL CHECK (
        sender_type IN ('customer', 'agent', 'human', 'system')
    ),
    body TEXT NOT NULL,
    external_message_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE,
    FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS escalations (
    id TEXT PRIMARY KEY,
    ticket_id TEXT,
    customer_id TEXT,
    reason TEXT NOT NULL,
    context TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'in_review', 'resolved')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE SET NULL,
    FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS email_drafts (
    id TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    original_ai_draft TEXT NOT NULL,
    human_edited_version TEXT,
    reviewer TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('draft', 'human_review', 'approved', 'rejected', 'sent')
    ),
    final_sent_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    sent_at TEXT,
    FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE,
    FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    actor_type TEXT NOT NULL CHECK (
        actor_type IN ('system', 'agent', 'human', 'customer')
    ),
    actor_id TEXT,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    customer_id TEXT,
    details TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sent_emails (
    id TEXT PRIMARY KEY,
    draft_id TEXT,
    ticket_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE,
    FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_jobs_customer_id ON jobs (customer_id);
CREATE INDEX IF NOT EXISTS idx_jobs_engineer_id ON jobs (assigned_engineer_id);
CREATE INDEX IF NOT EXISTS idx_invoices_customer_id ON invoices (customer_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices (status);
CREATE INDEX IF NOT EXISTS idx_tickets_category ON tickets (category);
CREATE INDEX IF NOT EXISTS idx_tickets_customer_id ON tickets (customer_id);
CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket_id ON ticket_messages (ticket_id);
CREATE INDEX IF NOT EXISTS idx_email_drafts_status ON email_drafts (status);
CREATE INDEX IF NOT EXISTS idx_sent_emails_ticket_id ON sent_emails (ticket_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON audit_log (resource_type, resource_id);
