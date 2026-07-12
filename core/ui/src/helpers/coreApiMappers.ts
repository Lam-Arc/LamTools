/**
 * Core API mappers — factory functions for mapping raw API shapes to Core UI types.
 *
 * Products share the same mapping structure but differ in:
 *   - groupId (product-specific)
 *   - nullable backend fields
 *
 * These factories let each product create a mapper with its own groupId and
 * null-handling strategy without duplicating the mapping logic.
 */

import type { CoreApiMapper, CoreSessionListItem, CoreMessage } from '../types';

// ---------------------------------------------------------------------------
// Raw-like types shared by product backends
// ---------------------------------------------------------------------------

/** Minimal shape a raw session object must satisfy for the session mapper. */
export type CoreSessionRawLike = {
  id: string;
  title: string;
  created_at: string | null;
  updated_at?: string | null;
  status?: string;
  metadata?: Record<string, unknown> | null;
};

/** Minimal shape a raw message object must satisfy for the message mapper. */
export type CoreMessageRawLike = {
  id: string;
  role: string;
  content: string;
  created_at: string | null;
  metadata?: Record<string, unknown> | null;
  /** Backend may attach product-specific parts payloads.
   *  Host views convert these into typed MessagePart[] for display. */
  parts?: unknown;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Normalize a raw role string to the CoreMessage role union.
 *  Only 'user', 'assistant', 'system' are valid; anything else falls back to
 *  'assistant' so the UI always has a renderable message. */
function normalizeRole(raw: string): CoreMessage['role'] {
  if (raw === 'user' || raw === 'assistant' || raw === 'system') return raw;
  return 'assistant';
}

// ---------------------------------------------------------------------------
// Session mapper factory
// ---------------------------------------------------------------------------

export interface CreateSessionMapperOptions {
  /** @deprecated nullFallback is no longer needed — the mapper now always
   *  converts null to safe defaults (createdAt → '', updatedAt/metadata → undefined). */
  nullFallback?: boolean;
}

/**
 * Create a `CoreApiMapper<CoreSessionRawLike, CoreSessionListItem>` bound to
 * the given groupId and null-handling strategy.
 */
export function createSessionMapper(
  groupId: string,
  _options?: CreateSessionMapperOptions,
): CoreApiMapper<CoreSessionRawLike, CoreSessionListItem> {

  return {
    toCore(raw: CoreSessionRawLike): CoreSessionListItem {
      return {
        id: raw.id,
        title: raw.title,
        createdAt: raw.created_at ?? '',
        updatedAt: raw.updated_at ?? undefined,
        groupId,
        status: raw.status,
        metadata: raw.metadata ?? undefined,
      };
    },

    toRaw(core: CoreSessionListItem): CoreSessionRawLike {
      return {
        id: core.id,
        title: core.title,
        created_at: core.createdAt,
        updated_at: core.updatedAt ?? null,
        status: core.status,
        metadata: core.metadata ?? null,
      };
    },
  };
}

// ---------------------------------------------------------------------------
// Message mapper factory
// ---------------------------------------------------------------------------

export interface CreateMessageMapperOptions {
  /** When true, nullable backend fields fall back to '' / undefined instead of
   *  being passed through as null. */
  nullFallback?: boolean;
}

/**
 * Create a `CoreApiMapper<CoreMessageRawLike, CoreMessage>` bound to the
 * given null-handling strategy.
 */
export function createMessageMapper(
  _options?: CreateMessageMapperOptions,
): CoreApiMapper<CoreMessageRawLike, CoreMessage> {

  return {
    toCore(raw: CoreMessageRawLike): CoreMessage {
      return {
        id: raw.id,
        role: normalizeRole(raw.role),
        content: raw.content,
        timestamp: raw.created_at ?? '',
        rawParts: raw.parts ?? undefined,
        metadata: raw.metadata ?? undefined,
      };
    },

    toRaw(core: CoreMessage): CoreMessageRawLike {
      return {
        id: core.id,
        role: core.role,
        content: core.content,
        created_at: core.timestamp,
        metadata: core.metadata ?? null,
        parts: core.rawParts ?? null,
      };
    },
  };
}
