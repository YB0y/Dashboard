const api = {
    async getRepos({ skip = 0, limit = 50, sort_by = "weight", search } = {}) {
        const params = new URLSearchParams({ skip, limit, sort_by });
        if (search) params.set("search", search);
        const res = await fetch(`/api/repos?${params}`);
        return res.json();
    },

    async getStats() {
        const res = await fetch("/api/stats");
        return res.json();
    },

    async getIssues({ repo, read_filter, limit = 40, skip = 0 } = {}) {
        const params = new URLSearchParams({ limit, skip });
        if (repo) params.set("repo", repo);
        if (read_filter) params.set("read_filter", read_filter);
        const res = await fetch(`/api/issues?${params}`);
        return res.json();
    },

    async getUnreadCount() {
        const res = await fetch("/api/issues/unread-count");
        return res.json();
    },

    async markIssueRead(githubId) {
        await fetch(`/api/issues/${githubId}/read`, { method: "POST" });
    },

    async markAllIssuesRead({ repo } = {}) {
        const params = new URLSearchParams();
        if (repo) params.set("repo", repo);
        await fetch(`/api/issues/read-all?${params}`, { method: "POST" });
    },

    async getNotifications(unreadOnly = false, limit = 50) {
        const params = new URLSearchParams({ unread_only: unreadOnly, limit });
        const res = await fetch(`/api/notifications?${params}`);
        return res.json();
    },

    async getNotifUnreadCount() {
        const res = await fetch("/api/notifications/count");
        return res.json();
    },

    async markAllNotifsRead() {
        await fetch("/api/notifications/read-all", { method: "POST" });
    },

    async togglePin(fullName) {
        const res = await fetch(`/api/repos/${encodeURIComponent(fullName)}/pin`, { method: "POST" });
        return res.json();
    },

    async getSlackSetting() {
        const res = await fetch("/api/settings/slack");
        return res.json();
    },

    async setSlackSetting(enabled) {
        const res = await fetch("/api/settings/slack", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled }),
        });
        return res.json();
    },
};
