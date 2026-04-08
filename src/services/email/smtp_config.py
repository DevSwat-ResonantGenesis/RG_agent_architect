"""SMTP Config — Custom email server setup via Secret fields"""
async def configure_smtp(workspace_id: str, params: dict) -> dict:
    return {"status": "configured", "host": params.get("smtp_host"), "from": params.get("from_email")}

async def delete_smtp(workspace_id: str) -> dict:
    return {"status": "reverted_to_mailgun"}
