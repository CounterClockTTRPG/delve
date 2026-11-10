// The Connections API (portraits plan Task 3): the owner's alone. A token goes in and never comes back out; the
// answers say only whether one is set.
import { apiFetch, deleteJson, postJson, putJson } from "../api";

export type ReplicateState = "unset" | "set" | "environment";
export type ConnectionName = "replicate" | "assetgen" | "google" | "email";

export interface ReplicateConnection {
  state: ReplicateState;
}

export interface AssetgenConnection {
  url: string | null;
  token: "set" | "unset";
}

/** Google's client for logging in with Google (DEL-206): its id (not secret), whether a secret is stored, and the
 * redirect URIs the owner registers with Google. */
export interface GoogleConnection {
  client_id: string | null;
  secret: "set" | "unset";
  redirect_uris: string[];
}

export type MailProviderName = "log" | "emailit";

/** The Email connection (DEL-314): which provider sends, the install's sender and public address, whether Emailit's key
 * is set (never the key), today's count and the latest failures. No address of anyone's. */
export interface EmailConnection {
  provider: MailProviderName;
  sender: string;
  public_url: string;
  public_url_default: string | null;
  key: ReplicateState;
  sent_today: number;
  waiting: number;
  failures: { kind: string; at: string; failure: string }[];
}

export interface ConnectionsState {
  replicate: ReplicateConnection;
  assetgen: AssetgenConnection;
  google?: GoogleConnection;
  email?: EmailConnection;
}

export interface ConnectionCheck {
  ok: boolean;
  message: string;
}

/** Where assetgen listens unless the owner says otherwise (`assetgen serve`'s default). */
export const DEFAULT_ASSETGEN_URL = "http://localhost:8765";

export const connectionsKey = ["connections"];

export const getConnections = () => apiFetch<ConnectionsState>("/api/connections");
export const putReplicate = (token: string) => putJson<ReplicateConnection>("/api/connections/replicate", { token });
export const deleteReplicate = () => deleteJson<ReplicateConnection>("/api/connections/replicate");
/** An absent `token` keeps the stored one. */
export const putAssetgen = (url: string, token?: string) =>
  putJson<AssetgenConnection>("/api/connections/assetgen", token === undefined ? { url } : { url, token });
export const deleteAssetgen = () => deleteJson<AssetgenConnection>("/api/connections/assetgen");
/** An absent `clientSecret` keeps the stored one. */
export const putGoogle = (clientId: string, clientSecret?: string) =>
  putJson<GoogleConnection>(
    "/api/connections/google",
    clientSecret === undefined ? { client_id: clientId } : { client_id: clientId, client_secret: clientSecret },
  );
/** Who runs this Delve, as the privacy policy and the terms show it (DEL-208). */
export const putOperator = (operator: { name: string; email: string }) =>
  putJson<{ operator: { name: string; email: string } }>("/api/legal", operator);
export const deleteGoogle = () => deleteJson<GoogleConnection>("/api/connections/google");
/** An absent `key` keeps the stored one. */
export const putEmail = (email: { provider: MailProviderName; sender: string; public_url: string; key?: string }) =>
  putJson<EmailConnection>("/api/connections/email", email);
export const deleteEmail = () => deleteJson<EmailConnection>("/api/connections/email");
export const checkConnection = (name: ConnectionName) => postJson<ConnectionCheck>(`/api/connections/${name}/test`);
