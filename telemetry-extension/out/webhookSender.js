"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.WebhookSender = void 0;
const extension_1 = require("./extension");
class WebhookSender {
    supabaseUrl;
    supabaseKey;
    constructor(supabaseUrl = '', supabaseKey = '') {
        this.supabaseUrl = supabaseUrl;
        this.supabaseKey = supabaseKey;
    }
    updateConfig(supabaseUrl, supabaseKey) {
        this.supabaseUrl = supabaseUrl;
        this.supabaseKey = supabaseKey;
    }
    getBaseUrl() {
        return `${this.supabaseUrl.replace(/\/$/, '')}/rest/v1/extension_events`;
    }
    getHeaders(extraHeaders = {}) {
        return {
            'Content-Type': 'application/json',
            'apikey': this.supabaseKey,
            'Authorization': `Bearer ${this.supabaseKey}`,
            ...extraHeaders
        };
    }
    async sendToSupabase(payload) {
        if (!this.supabaseUrl || !this.supabaseKey) {
            extension_1.logger.appendLine("[WARN] Supabase URL or Key not configured. Skipping Supabase send.");
            return false;
        }
        try {
            const deleted = await this.deleteEventByIdentity(payload.commit_id, payload.developer_id, payload.repository_name);
            if (!deleted) {
                return false;
            }
            const url = this.getBaseUrl();
            const headers = this.getHeaders({ 'Prefer': 'return=minimal' });
            const jsonBody = JSON.stringify(payload);
            extension_1.logger.appendLine(`[DEBUG] POST to: ${url}`);
            extension_1.logger.appendLine(`[DEBUG] Fetch POST Body: ${jsonBody}`);
            const response = await fetch(url, {
                method: 'POST',
                headers,
                body: jsonBody
            });
            if (!response.ok) {
                if (response.status === 409) {
                    extension_1.logger.appendLine(`[INFO] Commit ${payload.commit_id} already exists in Supabase (409). Treating as synced.`);
                    return true;
                }
                const errorText = await response.text();
                extension_1.logger.appendLine(`[ERROR] Supabase send failed: ${response.status} ${response.statusText}`);
                extension_1.logger.appendLine(`[DETAILS] ${errorText}`);
                return false;
            }
            extension_1.logger.appendLine(`[SUCCESS] Telemetry sent to Supabase table 'extension_events'`);
            return true;
        }
        catch (error) {
            extension_1.logger.appendLine(`[ERROR] Exception sending to Supabase: ${error}`);
            return false;
        }
    }
    async fetchRemoteCommitIds(developerId, repositoryName) {
        if (!this.supabaseUrl || !this.supabaseKey) {
            return [];
        }
        const params = new URLSearchParams({
            select: 'commit_id',
            developer_id: `eq.${developerId}`,
            repository_name: `eq.${repositoryName}`,
            limit: '5000'
        });
        const url = `${this.getBaseUrl()}?${params.toString()}`;
        extension_1.logger.appendLine(`[DEBUG] GET remote commit ids: ${url}`);
        try {
            const response = await fetch(url, {
                method: 'GET',
                headers: this.getHeaders()
            });
            if (!response.ok) {
                const errorText = await response.text();
                extension_1.logger.appendLine(`[ERROR] Failed to fetch remote commit ids: ${response.status} ${response.statusText}`);
                extension_1.logger.appendLine(`[DETAILS] ${errorText}`);
                return [];
            }
            const rows = await response.json();
            return rows.map(row => row.commit_id).filter((commitId) => Boolean(commitId));
        }
        catch (error) {
            extension_1.logger.appendLine(`[ERROR] Exception fetching remote commit ids: ${error}`);
            return [];
        }
    }
    async deleteEventByIdentity(commitId, developerId, repositoryName) {
        if (!this.supabaseUrl || !this.supabaseKey) {
            return false;
        }
        const params = new URLSearchParams({
            commit_id: `eq.${commitId}`,
            developer_id: `eq.${developerId}`,
            repository_name: `eq.${repositoryName}`
        });
        const url = `${this.getBaseUrl()}?${params.toString()}`;
        extension_1.logger.appendLine(`[DEBUG] DELETE existing event rows for commit ${commitId}`);
        try {
            const response = await fetch(url, {
                method: 'DELETE',
                headers: this.getHeaders({ 'Prefer': 'return=minimal' })
            });
            if (!response.ok) {
                const errorText = await response.text();
                extension_1.logger.appendLine(`[ERROR] Failed to delete existing rows for ${commitId}: ${response.status} ${response.statusText}`);
                extension_1.logger.appendLine(`[DETAILS] ${errorText}`);
                return false;
            }
            return true;
        }
        catch (error) {
            extension_1.logger.appendLine(`[ERROR] Exception deleting existing rows for ${commitId}: ${error}`);
            return false;
        }
    }
}
exports.WebhookSender = WebhookSender;
//# sourceMappingURL=webhookSender.js.map