'use client';
import { useApi } from './hooks';

/** Parâmetros liga/desliga públicos (menu Parâmetros do painel). O servidor também bloqueia; a interface só esconde. */
export type Features = {
  sales_paused: boolean; sales_paused_reason: string; signup_enabled: boolean; google_login_enabled: boolean;
  queue_mode_enabled: boolean; scheduled_mode_enabled: boolean; coupons_enabled: boolean; keyboard_mouse_enabled: boolean;
  public_streams_enabled: boolean; support_tickets_enabled: boolean; disabled_platforms: string[];
};

export function useFeatures(): Features | null {
  return useApi<Features>('/features', 60000).data;
}
