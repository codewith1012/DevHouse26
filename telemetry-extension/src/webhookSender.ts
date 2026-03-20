import { SupaBaseEvent } from './types';
import { logger } from './extension';

export class WebhookSender {
    private supabaseUrl: string;
    private supabaseKey: string;

    constructor(supabaseUrl: string = '', supabaseKey: string = '') {
        this.supabaseUrl = supabaseUrl;
        this.supabaseKey = supabaseKey;
    }

    public updateConfig(supabaseUrl: string, supabaseKey: string): void {
        this.supabaseUrl = supabaseUrl;
        this.supabaseKey = supabaseKey;
    }

    public async sendToSupabase(payload: SupaBaseEvent): Promise<boolean> {
        if (!this.supabaseUrl || !this.supabaseKey) {
            logger.appendLine("[WARN] Supabase URL or Key not configured. Skipping Supabase send.");
            return false;
        }

        const url = `${this.supabaseUrl.replace(/\/$/, '')}/rest/v1/extension_events`;
        const headers = {
            'Content-Type': 'application/json',
            'apikey': this.supabaseKey,
            'Authorization': `Bearer ${this.supabaseKey}`,
            'Prefer': 'return=minimal'
        };

        logger.appendLine(`[DEBUG] POST to: ${url}`);
        
        const jsonBody = JSON.stringify(payload);
        logger.appendLine(`[DEBUG] Fetch POST Body: ${jsonBody}`);

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: headers,
                body: jsonBody
            });

            if (!response.ok) {
                const errorText = await response.text();
                logger.appendLine(`[ERROR] Supabase send failed: ${response.status} ${response.statusText}`);
                logger.appendLine(`[DETAILS] ${errorText}`);
                return false;
            } else {
                logger.appendLine(`[SUCCESS] Telemetry sent to Supabase table 'extension_events'`);
                return true;
            }
        } catch (error) {
            logger.appendLine(`[ERROR] Exception sending to Supabase: ${error}`);
            return false;
        }
    }
}
