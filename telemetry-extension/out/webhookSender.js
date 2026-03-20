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
    async sendToSupabase(payload) {
        if (!this.supabaseUrl || !this.supabaseKey) {
            extension_1.logger.appendLine("[WARN] Supabase URL or Key not configured. Skipping Supabase send.");
            return false;
        }
        const url = `${this.supabaseUrl.replace(/\/$/, '')}/rest/v1/extension_events`;
        const headers = {
            'Content-Type': 'application/json',
            'apikey': this.supabaseKey,
            'Authorization': `Bearer ${this.supabaseKey}`,
            'Prefer': 'return=minimal'
        };
        extension_1.logger.appendLine(`[DEBUG] POST to: ${url}`);
        const jsonBody = JSON.stringify(payload);
        extension_1.logger.appendLine(`[DEBUG] Fetch POST Body: ${jsonBody}`);
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: headers,
                body: jsonBody
            });
            if (!response.ok) {
                const errorText = await response.text();
                extension_1.logger.appendLine(`[ERROR] Supabase send failed: ${response.status} ${response.statusText}`);
                extension_1.logger.appendLine(`[DETAILS] ${errorText}`);
                return false;
            }
            else {
                extension_1.logger.appendLine(`[SUCCESS] Telemetry sent to Supabase table 'extension_events'`);
                return true;
            }
        }
        catch (error) {
            extension_1.logger.appendLine(`[ERROR] Exception sending to Supabase: ${error}`);
            return false;
        }
    }
}
exports.WebhookSender = WebhookSender;
//# sourceMappingURL=webhookSender.js.map