from pydantic import BaseModel


class DashboardStats(BaseModel):
    total_repos: int
    total_open_issues: int
    unread_issues: int
