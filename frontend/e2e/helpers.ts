import { execSync } from 'node:child_process';
import { createHmac } from 'node:crypto';

const PSQL = process.env.E2E_PSQL || 'psql -h /tmp -U postgres locaplay';

/** Lê o último código de verificação da caixa de e-mails de DESENVOLVIMENTO (EMAIL_PROVIDER=dev). */
export function lastCode(email: string): string {
  const out = execSync(`${PSQL} -tAc "select body_text from dev_mailbox where to_address='${email.replace(/'/g, '')}' order by id desc limit 1"`).toString();
  const m = out.match(/\b(\d{6})\b/);
  if (!m) throw new Error('código não encontrado');
  return m[1];
}

/** Somente ambiente de teste: remove o MFA do admin de teste para o cenário ser repetível. */
export function resetAdminMfa(email: string) {
  execSync(`${PSQL} -qc "delete from mfa_factors where user_id=(select id from users where email='${email}'); delete from mfa_recovery_codes where user_id=(select id from users where email='${email}'); delete from rate_limit_buckets"`);
}

function base32(s: string): Buffer {
  const a = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const c of s.replace(/=+$/, '').toUpperCase()) bits += a.indexOf(c).toString(2).padStart(5, '0');
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

export function totp(secret: string, offsetSteps = 0): string {
  const counter = Math.floor(Date.now() / 30000) + offsetSteps;
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter));
  const h = createHmac('sha1', base32(secret)).update(buf).digest();
  const o = h[h.length - 1] & 0xf;
  const code = ((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).toString().padStart(6, '0');
  return code;
}

export const uid = () => Math.random().toString(36).slice(2, 8);
export const SHOTS = 'e2e/screenshots';
