'use client';

import { createContext, useContext, useRef, useState, type Dispatch, type SetStateAction } from 'react';

export type DraftFields = Record<string, unknown>;
export type RegistrationDraft = { version?: 2; step: number; furthest: number; fields: DraftFields };
export type RegistrationDrafts = Record<string, RegistrationDraft>;

export const DraftFieldsContext = createContext<DraftFields | null>(null);

export function useDraftValue<T>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>, boolean] {
  const fields = useContext(DraftFieldsContext);
  const cached = useRef(!!fields && Object.hasOwn(fields, key)).current;
  const [value, setValue] = useState<T>(() => cached ? fields![key] as T : initial);
  const latest = useRef(value);
  const update: Dispatch<SetStateAction<T>> = (change) => {
    const next = typeof change === 'function' ? (change as (previous: T) => T)(latest.current) : change;
    latest.current = next;
    if (fields) fields[key] = next;
    setValue(next);
  };
  return [value, update, cached];
}

export function readRegistrationDrafts(key: string): RegistrationDrafts {
  try {
    const drafts: RegistrationDrafts = JSON.parse(window.localStorage.getItem(key) ?? '{}') ?? {};
    return Object.fromEntries(Object.entries(drafts).map(([id, draft]) => [id, draft.version === 2 ? draft : {
      ...draft, version: 2, step: draft.step >= 4 ? draft.step + 1 : draft.step, furthest: draft.furthest >= 4 ? draft.furthest + 1 : draft.furthest,
    }]));
  }
  catch { return {}; }
}
