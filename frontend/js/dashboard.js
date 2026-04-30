const dashboard = {
    selectedRepo: null,
    currentPage: 0,
    pageSize: 50,
    sortBy: "recent",
    searchQuery: "",

    async loadRepos() {
        try {
            const { repos, total } = await api.getRepos({
                skip: this.currentPage * this.pageSize,
                limit: this.pageSize,
                sort_by: this.sortBy,
                search: this.searchQuery || undefined,
            });

            const grid = document.getElementById("repo-grid");
            if (repos.length === 0) {
                grid.innerHTML = '<div class="empty-state">No repositories found</div>';
                this.updateRepoPagination(0);
                return;
            }

            const startNum = this.currentPage * this.pageSize;
            grid.innerHTML = repos.map((repo, idx) => `
                <div class="repo-card ${repo.full_name === this.selectedRepo ? 'selected' : ''} ${repo.pinned ? 'pinned' : ''}"
                     data-repo="${utils.escapeHtml(repo.full_name)}">
                    <div class="repo-card-header">
                        <div class="repo-card-left">
                            <span class="repo-number">${startNum + idx + 1}</span>
                            <button class="pin-btn ${repo.pinned ? 'active' : ''}" data-pin="${utils.escapeHtml(repo.full_name)}" title="${repo.pinned ? 'Unpin repository' : 'Pin to top'}">
                                <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M4.456.734a1.75 1.75 0 0 1 2.826.504l.613 1.327a3.08 3.08 0 0 0 2.084 1.707l2.454.584c1.332.317 1.8 1.972.832 2.94L11.06 10l3.72 3.72a.75.75 0 1 1-1.06 1.06L10 11.06l-2.204 2.205c-.968.968-2.623.5-2.94-.832l-.584-2.454a3.08 3.08 0 0 0-1.707-2.084l-1.327-.613a1.75 1.75 0 0 1-.504-2.826L4.456.734Z"/></svg>
                            </button>
                            <span class="repo-name">${utils.escapeHtml(repo.full_name)}</span>
                        </div>
                        <div class="repo-card-badges">
                            ${repo.normal_unread ? `<span class="repo-unread-badge badge-normal" title="${repo.normal_unread} unread from community">${repo.normal_unread}</span>` : ''}
                            ${repo.maintainer_unread ? `<span class="repo-unread-badge badge-maintainer" title="${repo.maintainer_unread} unread from maintainers">${repo.maintainer_unread}</span>` : ''}
                        </div>
                    </div>
                    <div class="repo-description">${utils.escapeHtml(repo.description || "No description yet")}</div>
                    <div class="repo-stats">
                        <span title="GitHub Stars">&#9733; ${utils.formatNumber(repo.stars)}</span>
                        <span title="Forks">&#128374; ${utils.formatNumber(repo.forks)}</span>
                        <span title="Open Issues">&#9888; ${repo.open_issues_count}</span>
                        <span class="weight-badge" title="Gittensor Weight">W: ${repo.weight.toFixed(4)}</span>
                    </div>
                </div>
            `).join("");

            // Pin button click
            grid.querySelectorAll(".pin-btn").forEach(btn => {
                btn.addEventListener("click", async (e) => {
                    e.stopPropagation();
                    const fullName = btn.dataset.pin;
                    await api.togglePin(fullName);
                    this.loadRepos();
                });
            });

            // Repo card click
            grid.querySelectorAll(".repo-card").forEach(card => {
                card.addEventListener("click", (e) => {
                    if (e.target.closest(".pin-btn")) return;
                    this.selectRepo(card.dataset.repo);
                });
            });

            this.updateRepoPagination(total);
        } catch (e) {
            document.getElementById("repo-grid").innerHTML = '<div class="empty-state">Failed to load repositories</div>';
        }
    },

    updateRepoPagination(total) {
        const totalPages = Math.ceil(total / this.pageSize);
        document.getElementById("repo-prev").disabled = this.currentPage === 0;
        document.getElementById("repo-next").disabled = this.currentPage >= totalPages - 1;
        document.getElementById("repo-page-info").textContent =
            `Page ${this.currentPage + 1} of ${totalPages || 1} (${total} repos)`;
    },

    selectRepo(fullName) {
        this.selectedRepo = fullName === this.selectedRepo ? null : fullName;
        this.loadRepos();
        issues.currentPage = 0;
        issues.loadIssues();
    },

    updateCounts(stats) {
        const label = document.getElementById("count-all-label");
        if (label) {
            label.textContent = `${stats.total_repos} repositories`;
        }
    },
};
