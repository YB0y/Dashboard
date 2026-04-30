const issues = {
    currentPage: 0,
    pageSize: 40,
    readFilter: "",

    async loadIssues() {
        try {
            const { issues: data, total } = await api.getIssues({
                repo: dashboard.selectedRepo,
                read_filter: this.readFilter || undefined,
                limit: this.pageSize,
                skip: this.currentPage * this.pageSize,
            });

            // Update header
            const title = document.getElementById("issues-title");
            const subtitle = document.getElementById("issues-subtitle");
            if (dashboard.selectedRepo) {
                title.textContent = `Issues: ${dashboard.selectedRepo}`;
                subtitle.textContent = `${total} open issues in this repo`;
            } else {
                title.textContent = "Latest Issues (All Repos)";
                subtitle.textContent = `${total} open issues across all monitored repos`;
            }

            const list = document.getElementById("issues-list");
            if (data.length === 0) {
                list.innerHTML = '<div class="empty-state">No issues found. The poller will discover new issues shortly.</div>';
            } else {
                list.innerHTML = data.map(issue => `
                    <div class="issue-item ${issue.read ? '' : 'unread'}" data-github-id="${issue.github_id}">
                        <div class="issue-read-indicator" title="${issue.read ? 'Read' : 'Unread - Click to mark as read'}"></div>
                        <div class="issue-content">
                            <div class="issue-header">
                                <a href="${utils.escapeHtml(issue.html_url)}" target="_blank" rel="noopener" class="issue-title">
                                    #${issue.number}: ${utils.escapeHtml(issue.title)}
                                </a>
                                <span class="issue-repo-tag">${utils.escapeHtml(issue.repo_full_name)}</span>
                            </div>
                            ${(issue.labels && issue.labels.length) ? `
                                <div class="issue-labels">
                                    ${issue.labels.map(l => `<span class="label">${utils.escapeHtml(l)}</span>`).join("")}
                                </div>
                            ` : ""}
                            <div class="issue-meta">
                                by <strong>${utils.escapeHtml(issue.author)}</strong>
                                ${issue.author_role ? `<span class="author-role role-${(issue.author_role || '').toLowerCase()}">${issue.author_role}</span>` : ''}
                                &middot; ${utils.timeAgo(issue.created_at)}
                            </div>
                            ${issue.body ? `<div class="issue-body-preview">${utils.escapeHtml(utils.truncate(issue.body, 150))}</div>` : ""}
                        </div>
                        ${!issue.read ? `<button class="mark-read-btn" data-gid="${issue.github_id}" title="Mark as read">Mark Read</button>` : ''}
                    </div>
                `).join("");

                // Click unread indicator to mark as read
                list.querySelectorAll(".issue-item.unread .issue-read-indicator").forEach(dot => {
                    dot.addEventListener("click", async (e) => {
                        e.stopPropagation();
                        const item = dot.closest(".issue-item");
                        const githubId = parseInt(item.dataset.githubId);
                        await api.markIssueRead(githubId);
                        item.classList.remove("unread");
                        dot.title = "Read";
                        const btn = item.querySelector(".mark-read-btn");
                        if (btn) btn.remove();
                        this.updateUnreadStat();
                        dashboard.loadRepos();
                    });
                });

                // Mark Read button click
                list.querySelectorAll(".mark-read-btn").forEach(btn => {
                    btn.addEventListener("click", async (e) => {
                        e.stopPropagation();
                        const githubId = parseInt(btn.dataset.gid);
                        await api.markIssueRead(githubId);
                        const item = btn.closest(".issue-item");
                        item.classList.remove("unread");
                        const dot = item.querySelector(".issue-read-indicator");
                        if (dot) dot.title = "Read";
                        btn.remove();
                        this.updateUnreadStat();
                        dashboard.loadRepos();
                    });
                });

                // Click issue row to open and mark read
                list.querySelectorAll(".issue-item").forEach(item => {
                    item.addEventListener("click", async (e) => {
                        if (e.target.closest("a")) return; // let links work normally
                        const githubId = parseInt(item.dataset.githubId);
                        const issue = data.find(i => i.github_id === githubId);
                        if (issue) {
                            window.open(issue.html_url, "_blank");
                            if (!issue.read) {
                                await api.markIssueRead(githubId);
                                item.classList.remove("unread");
                                this.updateUnreadStat();
                            }
                        }
                    });
                });
            }

            // Pagination
            const totalPages = Math.ceil(total / this.pageSize);
            document.getElementById("issues-prev").disabled = this.currentPage === 0;
            document.getElementById("issues-next").disabled = this.currentPage >= totalPages - 1;
            document.getElementById("issues-page-info").textContent = `Page ${this.currentPage + 1} of ${totalPages || 1}`;
        } catch (e) {
            document.getElementById("issues-list").innerHTML = '<div class="empty-state">Failed to load issues</div>';
        }
    },

    async updateUnreadStat() {
        try {
            const { count } = await api.getUnreadCount();
            document.getElementById("stat-unread").textContent = `${count} Unread`;
        } catch (e) {}
    },
};
