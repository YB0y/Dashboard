document.addEventListener("DOMContentLoaded", async () => {
    // 1. Load initial data
    await dashboard.loadRepos();
    await issues.loadIssues();
    await notifs.updateBadge();

    // 2. Load and display stats
    try {
        const stats = await api.getStats();
        updateStatsDisplay(stats);
    } catch (e) {}

    // 3. Connect WebSocket for real-time updates
    const ws = new DashboardWebSocket(
        (data) => {
            if (data.event === "new_issue") {
                // Show toast notification
                notifs.showToast(data);
                notifs.updateBadge();
                // Refresh data
                setTimeout(() => {
                    dashboard.loadRepos();
                    issues.loadIssues();
                    issues.updateUnreadStat();
                }, 300);
            } else if (data.event === "stats_update") {
                updateStatsDisplay(data);
            }
        },
        (status) => {
            const el = document.getElementById("stat-connection");
            if (status === "connected") {
                el.textContent = "Live";
                el.classList.add("connected");
            } else {
                el.textContent = "Reconnecting...";
                el.classList.remove("connected");
            }
        }
    );
    ws.connect();

    // 4. Search
    let searchTimeout;
    document.getElementById("search-input").addEventListener("input", (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            dashboard.searchQuery = e.target.value.trim();
            dashboard.currentPage = 0;
            dashboard.loadRepos();
        }, 300);
    });

    // 6. Sort
    document.getElementById("repo-sort").addEventListener("change", (e) => {
        dashboard.sortBy = e.target.value;
        dashboard.currentPage = 0;
        dashboard.loadRepos();
    });

    // 7. Read filter
    document.getElementById("read-filter").addEventListener("change", (e) => {
        issues.readFilter = e.target.value;
        issues.currentPage = 0;
        issues.loadIssues();
    });

    // 8. Mark all issues read
    document.getElementById("mark-all-read-btn").addEventListener("click", async () => {
        await api.markAllIssuesRead({
            repo: dashboard.selectedRepo,
        });
        issues.loadIssues();
        issues.updateUnreadStat();
    });

    // 9. Notification bell
    document.getElementById("notification-bell").addEventListener("click", () => {
        const panel = document.getElementById("notification-panel");
        panel.classList.toggle("hidden");
        if (!panel.classList.contains("hidden")) {
            notifs.loadPanel();
        }
    });

    // 10. Dismiss all notifications
    document.getElementById("mark-all-notif-read-btn").addEventListener("click", async () => {
        await api.markAllNotifsRead();
        notifs.updateBadge();
        notifs.loadPanel();
    });

    // 11. Repo pagination
    document.getElementById("repo-prev").addEventListener("click", () => {
        if (dashboard.currentPage > 0) {
            dashboard.currentPage--;
            dashboard.loadRepos();
        }
    });
    document.getElementById("repo-next").addEventListener("click", () => {
        dashboard.currentPage++;
        dashboard.loadRepos();
    });

    // 12. Issues pagination
    document.getElementById("issues-prev").addEventListener("click", () => {
        if (issues.currentPage > 0) {
            issues.currentPage--;
            issues.loadIssues();
        }
    });
    document.getElementById("issues-next").addEventListener("click", () => {
        issues.currentPage++;
        issues.loadIssues();
    });

    // 13. Slack alert toggle
    initSlackToggle();

    // 14. Close notification panel on outside click
    document.addEventListener("click", (e) => {
        const panel = document.getElementById("notification-panel");
        const bell = document.getElementById("notification-bell");
        if (!panel.contains(e.target) && !bell.contains(e.target)) {
            panel.classList.add("hidden");
        }
    });
});

async function initSlackToggle() {
    const btn = document.getElementById("slack-toggle");
    const state = document.getElementById("slack-toggle-state");
    if (!btn || !state) return;

    const render = ({ enabled, webhook_configured }) => {
        btn.classList.toggle("on", enabled);
        btn.classList.toggle("off", !enabled);
        btn.setAttribute("aria-pressed", String(!!enabled));
        state.textContent = enabled ? "ON" : "OFF";
        if (!webhook_configured) {
            btn.disabled = true;
            btn.title = "No SLACK_WEBHOOK_URL configured in .env";
            state.textContent = "N/A";
        } else {
            btn.title = enabled
                ? "Slack alerts ON — click to disable"
                : "Slack alerts OFF — click to enable";
        }
    };

    try {
        const cur = await api.getSlackSetting();
        render(cur);

        btn.addEventListener("click", async () => {
            if (btn.disabled) return;
            const next = !btn.classList.contains("on");
            const result = await api.setSlackSetting(next);
            render({ enabled: result.enabled, webhook_configured: true });
        });
    } catch (e) {
        state.textContent = "?";
    }
}

function updateStatsDisplay(stats) {
    document.getElementById("stat-repos").textContent = `${stats.total_repos} Repos`;
    document.getElementById("stat-issues").textContent = `${stats.total_open_issues} Open Issues`;
    document.getElementById("stat-unread").textContent = `${stats.unread_issues} Unread`;
    dashboard.updateCounts(stats);
}
