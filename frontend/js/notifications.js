const notifs = {
    showToast(data) {
        const container = document.getElementById("toast-container");
        const toast = document.createElement("div");
        toast.className = "toast";
        toast.innerHTML = `
            <div class="toast-header">
                <span class="toast-repo">${utils.escapeHtml(data.repo_full_name)}</span>
            </div>
            <div class="toast-body">
                <a href="${utils.escapeHtml(data.issue_url)}" target="_blank" rel="noopener">
                    #${data.issue_number}: ${utils.escapeHtml(data.issue_title)}
                </a>
                <span class="toast-author">by ${utils.escapeHtml(data.author)}</span>
            </div>
        `;
        toast.addEventListener("click", () => window.open(data.issue_url, "_blank"));
        container.prepend(toast);
        setTimeout(() => toast.remove(), 9000);
    },

    async updateBadge() {
        try {
            const { count } = await api.getNotifUnreadCount();
            const badge = document.getElementById("notification-badge");
            badge.textContent = count;
            badge.classList.toggle("hidden", count === 0);
        } catch (e) {}
    },

    async loadPanel() {
        try {
            const items = await api.getNotifications(false, 100);
            const list = document.getElementById("notification-list");
            if (items.length === 0) {
                list.innerHTML = '<div class="notification-empty">No new issue alerts yet</div>';
                return;
            }
            list.innerHTML = items.map(n => `
                <div class="notif-item ${n.read ? '' : 'unread'}" data-github-id="${n.github_id}">
                    <div class="notif-dot"></div>
                    <div class="notif-content">
                        <div class="notif-message">
                            <strong>${utils.escapeHtml(n.repo_full_name)}</strong>
                            #${n.issue_number}: ${utils.escapeHtml(n.issue_title)}
                        </div>
                        <div class="notif-meta">by ${utils.escapeHtml(n.author)} &middot; ${utils.timeAgo(n.created_at)}</div>
                    </div>
                </div>
            `).join("");

            // Click a notification to open issue and mark as read
            list.querySelectorAll(".notif-item").forEach(item => {
                item.addEventListener("click", async () => {
                    const githubId = parseInt(item.dataset.githubId);
                    const n = items.find(x => x.github_id === githubId);
                    if (n) window.open(n.issue_url, "_blank");
                });
            });
        } catch (e) {}
    },
};
