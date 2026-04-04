import { SupaBaseEvent } from './types';
import { logger } from './extension';

export class WebhookSender {
    private supabaseUrl: string;
    private supabaseKey: string;
    private estimateEngineUrl: string;

    constructor(supabaseUrl: string = '', supabaseKey: string = '', estimateEngineUrl: string = '') {
        this.supabaseUrl = supabaseUrl;
        this.supabaseKey = supabaseKey;
        this.estimateEngineUrl = estimateEngineUrl;
    }

    public updateConfig(supabaseUrl: string, supabaseKey: string, estimateEngineUrl: string = ''): void {
        this.supabaseUrl = supabaseUrl;
        this.supabaseKey = supabaseKey;
        this.estimateEngineUrl = estimateEngineUrl;
    }

    private getBaseUrl(): string {
        return `${this.supabaseUrl.replace(/\/$/, '')}/rest/v1/extension_events`;
    }

    private getHeaders(extraHeaders: Record<string, string> = {}): Record<string, string> {
        return {
            'Content-Type': 'application/json',
            'apikey': this.supabaseKey,
            'Authorization': `Bearer ${this.supabaseKey}`,
            ...extraHeaders
        };
    }

    public async sendToSupabase(payload: SupaBaseEvent): Promise<boolean> {
        if (!this.supabaseUrl || !this.supabaseKey) {
            logger.appendLine("[WARN] Supabase URL or Key not configured. Skipping Supabase send.");
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
            logger.appendLine(`[DEBUG] POST to: ${url}`);
            logger.appendLine(`[DEBUG] Fetch POST Body: ${jsonBody}`);

            const response = await fetch(url, {
                method: 'POST',
                headers,
                body: jsonBody
            });

            if (!response.ok) {
                if (response.status === 409) {
                    logger.appendLine(`[INFO] Commit ${payload.commit_id} already exists in Supabase (409). Treating as synced.`);
                    return true;
                }
                const errorText = await response.text();
                logger.appendLine(`[ERROR] Supabase send failed: ${response.status} ${response.statusText}`);
                logger.appendLine(`[DETAILS] ${errorText}`);
                return false;
            }

            logger.appendLine(`[SUCCESS] Telemetry sent to Supabase table 'extension_events'`);
            return true;
        } catch (error) {
            logger.appendLine(`[ERROR] Exception sending to Supabase: ${error}`);
            return false;
        }
    }

    public async sendToEstimateEngine(payload: SupaBaseEvent): Promise<boolean> {
        if (!this.estimateEngineUrl) {
            logger.appendLine("[WARN] Estimate Engine URL not configured. Skipping estimate engine send.");
            return false;
        }

        const url = `${this.estimateEngineUrl.replace(/\/$/, '')}/signals/extension`;
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errorText = await response.text();
                logger.appendLine(`[ERROR] Estimate Engine send failed: ${response.status} ${response.statusText}`);
                logger.appendLine(`[DETAILS] ${errorText}`);
                return false;
            }

            logger.appendLine(`[SUCCESS] Telemetry sent to Estimate Engine endpoint '${url}'`);
            return true;
        } catch (error) {
            logger.appendLine(`[ERROR] Exception sending to Estimate Engine: ${error}`);
            return false;
        }
    }

    public async fetchRemoteCommitIds(developerId: string, repositoryName: string): Promise<string[]> {
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
        logger.appendLine(`[DEBUG] GET remote commit ids: ${url}`);

        try {
            const response = await fetch(url, {
                method: 'GET',
                headers: this.getHeaders()
            });

            if (!response.ok) {
                const errorText = await response.text();
                logger.appendLine(`[ERROR] Failed to fetch remote commit ids: ${response.status} ${response.statusText}`);
                logger.appendLine(`[DETAILS] ${errorText}`);
                return [];
            }

            const rows = await response.json() as Array<{ commit_id?: string }>;
            return rows.map(row => row.commit_id).filter((commitId): commitId is string => Boolean(commitId));
        } catch (error) {
            logger.appendLine(`[ERROR] Exception fetching remote commit ids: ${error}`);
            return [];
        }
    }

    public async deleteEventByIdentity(commitId: string, developerId: string, repositoryName: string): Promise<boolean> {
        if (!this.supabaseUrl || !this.supabaseKey) {
            return false;
        }

        const params = new URLSearchParams({
            commit_id: `eq.${commitId}`,
            developer_id: `eq.${developerId}`,
            repository_name: `eq.${repositoryName}`
        });
        const url = `${this.getBaseUrl()}?${params.toString()}`;
        logger.appendLine(`[DEBUG] DELETE existing event rows for commit ${commitId}`);

        try {
            const response = await fetch(url, {
                method: 'DELETE',
                headers: this.getHeaders({ 'Prefer': 'return=minimal' })
            });

            if (!response.ok) {
                const errorText = await response.text();
                logger.appendLine(`[ERROR] Failed to delete existing rows for ${commitId}: ${response.status} ${response.statusText}`);
                logger.appendLine(`[DETAILS] ${errorText}`);
                return false;
            }

            return true;
        } catch (error) {
            logger.appendLine(`[ERROR] Exception deleting existing rows for ${commitId}: ${error}`);
            return false;
        }
    }
}
