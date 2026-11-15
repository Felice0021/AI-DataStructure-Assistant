import { request } from './http'

export type CloudPurpose = 'embedding' | 'reranking' | 'generation'
export interface CloudConsent {
  purpose: CloudPurpose
  model: string
  revoked_at: string | null
  service_key: string
}
export interface CloudTarget { purpose: CloudPurpose; model: string; service_key: string }

export const cloudConsentApi = {
  list: (id: string): Promise<CloudConsent[]> => request(`/knowledge-bases/${encodeURIComponent(id)}/cloud-consents`),
  targets: (id: string): Promise<CloudTarget[]> => request(`/knowledge-bases/${encodeURIComponent(id)}/cloud-consents/targets`),
  change: (id: string, purpose: CloudPurpose, grant: boolean, serviceKey: string): Promise<CloudConsent> =>
    request(`/knowledge-bases/${encodeURIComponent(id)}/cloud-consents/${purpose}`, {
      method: grant ? 'POST' : 'DELETE',
      body: { expected_service_key: serviceKey },
    }),
}
