/**
 * Tests for client-side card tokenisation utility (Story 1.10).
 *
 * Critical security requirement: raw PAN must be tokenised BEFORE leaving the browser.
 * Only token + last-4 digits should ever be sent to the API.
 *
 * @see tokenize.ts
 */

import { describe, it, expect } from 'vitest';
import { tokenizeCard } from './tokenize';

describe('tokenizeCard', () => {
  describe('token generation', () => {
    it('generates a UUID v4 token for a valid 16-digit PAN', () => {
      const pan = '4242424242424242';
      const result = tokenizeCard(pan);

      // UUID v4 format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
      expect(result.token).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    });

    it('generates different tokens for the same PAN (each call is independent)', () => {
      const pan = '4242424242424242';
      const result1 = tokenizeCard(pan);
      const result2 = tokenizeCard(pan);

      expect(result1.token).not.toBe(result2.token);
    });

    it('generates different tokens for different PANs', () => {
      const result1 = tokenizeCard('4242424242424242');
      const result2 = tokenizeCard('5555555555554444');

      expect(result1.token).not.toBe(result2.token);
    });
  });

  describe('last-4 extraction', () => {
    it('extracts the last 4 digits from a 16-digit PAN', () => {
      const pan = '4242424242424242';
      const result = tokenizeCard(pan);

      expect(result.last4).toBe('4242');
    });

    it('extracts the last 4 digits from a 15-digit PAN', () => {
      const pan = '378282243310005'; // Amex example
      const result = tokenizeCard(pan);

      expect(result.last4).toBe('0005');
    });

    it('extracts the last 4 digits from a 13-digit PAN', () => {
      const pan = '4222222222222'; // Old Visa format
      const result = tokenizeCard(pan);

      expect(result.last4).toBe('2222');
    });
  });

  describe('security - PAN never included in output', () => {
    it('does NOT include the full PAN anywhere in the returned object', () => {
      const pan = '4242424242424242';
      const result = tokenizeCard(pan);

      const serialized = JSON.stringify(result);
      expect(serialized).not.toContain(pan);
    });

    it('does NOT include any 13-19 digit sequence in the output', () => {
      const pans = [
        '4242424242424242', // 16 digits
        '378282243310005', // 15 digits
        '4222222222222', // 13 digits
      ];

      for (const pan of pans) {
        const result = tokenizeCard(pan);
        const serialized = JSON.stringify(result);

        // Check for no 13-19 consecutive digits
        expect(serialized).not.toMatch(/\d{13,19}/);
      }
    });

    it('only exposes token (UUID) and last4 in the output structure', () => {
      const pan = '4242424242424242';
      const result = tokenizeCard(pan);

      expect(Object.keys(result)).toEqual(['token', 'last4']);
      expect(typeof result.token).toBe('string');
      expect(typeof result.last4).toBe('string');
    });
  });

  describe('input validation', () => {
    it('handles whitespace in PAN input', () => {
      const pan = '4242 4242 4242 4242';
      const result = tokenizeCard(pan);

      expect(result.token).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
      expect(result.last4).toBe('4242');
    });

    it('handles hyphens in PAN input', () => {
      const pan = '4242-4242-4242-4242';
      const result = tokenizeCard(pan);

      expect(result.token).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
      expect(result.last4).toBe('4242');
    });

    it('handles short PANs (<13 digits) gracefully', () => {
      const pan = '123456789'; // 9 digits
      const result = tokenizeCard(pan);

      expect(result.token).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
      expect(result.last4).toBe('6789');
    });

    it('handles long PANs (>19 digits) gracefully', () => {
      const pan = '12345678901234567890'; // 20 digits
      const result = tokenizeCard(pan);

      expect(result.token).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
      expect(result.last4).toBe('7890');
    });
  });

  describe('output format consistency', () => {
    it('always returns token as a UUID v4 string', () => {
      const results = [
        tokenizeCard('4242424242424242'),
        tokenizeCard('5555555555554444'),
        tokenizeCard('378282243310005'),
      ];

      for (const result of results) {
        expect(result.token).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
      }
    });

    it('always returns last4 as exactly 4 digits', () => {
      const results = [
        tokenizeCard('4242424242424242'),
        tokenizeCard('5555555555554444'),
        tokenizeCard('378282243310005'),
      ];

      for (const result of results) {
        expect(result.last4).toMatch(/^\d{4}$/);
      }
    });
  });

  describe('simulated tokenisation behavior', () => {
    it('generates opaque tokens that reveal nothing about the original PAN', () => {
      const similarPans = [
        '4242424242424242',
        '4242424242424243', // Last digit different
        '4242424242424252', // Second-to-last digit different
      ];

      const results = similarPans.map(tokenizeCard);

      // Tokens should be completely different (no sequential pattern)
      const tokens = results.map((r) => r.token);
      expect(new Set(tokens).size).toBe(3); // All unique

      // No similarity in token patterns
      expect(tokens[0]).not.toContain('4242');
      expect(tokens[1]).not.toContain('4243');
      expect(tokens[2]).not.toContain('4252');
    });
  });
});
