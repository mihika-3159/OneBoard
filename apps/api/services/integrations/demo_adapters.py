from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

class DemoCRMAdapter:
    """Simulated local CRM providing pipeline, contacts, and deal stages without external API."""
    def get_contacts(self) -> List[Dict[str, Any]]:
        return [
            {"id": "c1", "name": "Sarah Chen", "company": "Acme Technologies", "status": "active", "mrr": 490.0, "health": 92},
            {"id": "c2", "name": "Marcus Vance", "company": "Vance Logistics", "status": "active", "mrr": 590.0, "health": 78},
            {"id": "c3", "name": "Elena Rostova", "company": "FinEdge Advisory", "status": "active", "mrr": 890.0, "health": 95},
            {"id": "c4", "name": "David Kim", "company": "Nova Labs", "status": "onboarding", "mrr": 490.0, "health": 65}
        ]

class DemoFinanceAdapter:
    """Local finance ledger adapter."""
    def get_summary(self) -> Dict[str, Any]:
        return {
            "mrr": 18450.0,
            "monthly_burn": 12200.0,
            "net_margin": 6250.0,
            "cash_on_hand": 132840.0,
            "runway_months": 7.2,
            "overdue_invoices_count": 3,
            "overdue_amount": 4200.0
        }

class DemoEmailAdapter:
    """Simulated local email service for drafts and outbox."""
    def __init__(self):
        self.outbox = []

    def send_email(self, recipient: str, subject: str, body: str) -> Dict[str, Any]:
        record = {
            "id": f"mail_{len(self.outbox) + 1}",
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "status": "delivered",
            "timestamp": datetime.utcnow().isoformat()
        }
        self.outbox.append(record)
        return record

class DemoCalendarAdapter:
    """Local calendar adapter for executive schedules and reviews."""
    def get_events(self) -> List[Dict[str, Any]]:
        now = datetime.utcnow()
        return [
            {"title": "Weekly Board Review", "start": (now + timedelta(days=2)).isoformat(), "attendees": ["Founder", "Chief of Staff"]},
            {"title": "Sprint Planning: Custom Exporter Delivery", "start": (now + timedelta(days=3)).isoformat(), "attendees": ["Founder", "Sarah Chen"]},
            {"title": "Monthly Financial Close", "start": (now + timedelta(days=6)).isoformat(), "attendees": ["Founder", "Finance Adviser"]}
        ]

class GitHubAdapter:
    """Local GitHub adapter inspecting issues, PRs, and branch status."""
    def get_repo_status(self) -> Dict[str, Any]:
        return {
            "connected": True,
            "repo": "northstar-studio/core-platform",
            "open_issues": 14,
            "open_prs": 2,
            "recent_commits": [
                {"sha": "a7b3c21", "message": "feat: add webhook event triggers", "author": "Founder"},
                {"sha": "8f90d12", "message": "fix: invoice calculation edge case", "author": "Founder"}
            ]
        }

class NotionAdapter:
    """Notion database and page sync adapter."""
    def get_synced_databases(self) -> List[Dict[str, Any]]:
        return [
            {"id": "notion_db_1", "name": "Company Strategy & OKRs", "items_count": 12, "last_synced": datetime.utcnow().isoformat()},
            {"id": "notion_db_2", "name": "Product Spec: Webhook Exporter", "items_count": 5, "last_synced": datetime.utcnow().isoformat()}
        ]

class ChatConversationImportAdapter:
    """Parses exported ChatGPT / Claude conversations into structured business facts."""
    def parse_chat_export(self, raw_text: str) -> Dict[str, Any]:
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        decisions_found = []
        tasks_found = []
        for line in lines:
            lower = line.lower()
            if "decided" in lower or "agreed" in lower:
                decisions_found.append(line)
            elif "todo" in lower or "action item" in lower or "need to" in lower:
                tasks_found.append(line)
        return {
            "total_lines_analyzed": len(lines),
            "extracted_decisions": decisions_found,
            "extracted_tasks": tasks_found
        }

demo_crm = DemoCRMAdapter()
demo_finance = DemoFinanceAdapter()
demo_email = DemoEmailAdapter()
demo_calendar = DemoCalendarAdapter()
github_adapter = GitHubAdapter()
notion_adapter = NotionAdapter()
chat_import_adapter = ChatConversationImportAdapter()
