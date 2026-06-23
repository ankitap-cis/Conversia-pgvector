# requires psycopg2
import psycopg2
from psycopg2.extras import execute_values
from logger import *

RESOURCES = ["user_management"]
ACTIONS = ["create","get","view","update","delete","list"]
# ACTIONS = ["assign","bulk_assign","get_assigned","remove_assigned"]

def generate_perms():
    return [(f"{r}.{a}", f"{r} {a} permission") for r in RESOURCES for a in ACTIONS]

def upsert_permissions(conn, perms):
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
          id SERIAL PRIMARY KEY,
          code TEXT UNIQUE NOT NULL,
          description TEXT
        );""")
        execute_values(cur,
            "INSERT INTO permissions (code, description) VALUES %s ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description",
            perms
        )
    conn.commit()

if __name__ == "__main__":
    conn = psycopg2.connect("postgresql://postgres:postgres@localhost:5432/conversia")
    upsert_permissions(conn, generate_perms())
    logger.info("Permissions upserted")

# for manually adding permission to roles and permission table
"""

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code IN ('courses.view','courses.get','courses.create','courses.list','courses.delete','scenario.view','scenario.get','scenario.create','scenario.update','scenario.list','scenario.delete','persona.create','persona.update','persona.list','persona.get','persona.view','persona.delete','evaluation.create','evaluation.update','evaluation.list','evaluation.view','evaluation.get','evaluation.delete','knowledgebase.create','knowledgebase.update','knowledgebase.list','knowledgebase.view','knowledgebase.get','knowledgebase.delete')
WHERE r.name = 'content_creator'
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code IN ('courses.view','courses.get','courses.list','scenario.view','scenario.get','scenario.list','persona.list','persona.get','persona.view','evaluation.list','evaluation.view','evaluation.get','knowledgebase.list','knowledgebase.view','knowledgebase.get')
WHERE r.name = 'exec_viewer'
ON CONFLICT DO NOTHING;
"""