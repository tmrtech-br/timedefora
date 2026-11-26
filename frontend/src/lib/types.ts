export type Platform = { code: string; name: string; family: string };
export type GameCard = {
  id: string; slug: string; title: string; cover_url: string | null; banner_url: string | null; short_description: string;
  platforms: Platform[]; genres: string[]; release_date: string | null; is_demo: boolean; status: string; status_label: string;
  queue_size: number; estimated_wait_minutes: number | null; next_start_at: string | null; starting_price_cents: number | null;
};
export type Me = {
  id: string; full_name: string; username: string; email: string; status: string; avatar_url: string | null;
  email_verified: boolean; roles: string[]; mfa_enabled: boolean; mfa_verified: boolean; has_password: boolean;
  permission_overrides?: Record<string, boolean>;
  unread_notifications: number; marketing_opt_in: boolean; created_at: string;
};
export type QueueItem = { position: number; status: string; username: string; minutes: number; estimated_start_at: string; estimated_end_at: string; is_me: boolean };
export type Reservation = {
  id: string; code: string; status: string; mode: string; minutes: number; starts_at: string; ends_at: string;
  price_cents: number; discount_cents: number; total_cents: number; hold_expires_at: string | null; created_at: string;
  cancel_reason: string | null; resolution_notes: string | null; server_time: string;
  game: { title: string; slug: string; cover_url: string | null }; console_name: string;
  queue: { position: number; status: string } | null; session: { id: string; status: string } | null;
  payment: { id: string; status: string; method: string; checkout_url: string | null; provider: string } | null;
  cancellation_request: { status: string; decision_notes: string | null } | null;
  public_queue?: QueueItem[];
};
