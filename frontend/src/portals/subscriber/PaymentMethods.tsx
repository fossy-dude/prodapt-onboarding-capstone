/**
 * Payment Methods management page (Story 1.10).
 *
 * Allows authenticated subscribers to add, list, set default, and delete
 * saved payment methods. Card numbers are tokenised client-side before
 * any network call (see tokenize.ts).
 *
 * @see AC #1, #4, #5 - Payment methods UI functionality
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { addPaymentMethod, deletePaymentMethod, getPaymentMethods, setDefaultPaymentMethod } from '../../lib/api';
import { tokenizeCard } from '../../lib/tokenize';
import type { PaymentMethodType } from '../../types/payment-method';

import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';

/**
 * Mapping of payment method types to display icons and labels.
 */
const PAYMENT_METHOD_CONFIG = {
  CREDIT_CARD: { icon: '💳', label: 'Credit Card' },
  UPI: { icon: '📱', label: 'UPI ID' },
  NET_BANKING: { icon: '🏦', label: 'Net Banking' },
  MOBILE_WALLET: { icon: '👛', label: 'Mobile Wallet' },
} as const;

/**
 * Form state for adding a new payment method.
 */
interface AddPaymentMethodForm {
  type: PaymentMethodType;
  identifier: string; // Raw card number, UPI ID, bank name, or wallet handle
}

/**
 * Payment Methods page component.
 *
 * Renders the list of saved methods and a form to add new ones.
 * For credit cards, the identifier is tokenised client-side.
 */
export function PaymentMethods() {
  const queryClient = useQueryClient();

  // Server state: list of payment methods
  const { data: paymentMethodsData, isLoading, error } = useQuery({
    queryKey: ['payment-methods'],
    queryFn: getPaymentMethods,
  });

  // Mutations
  const addMutation = useMutation({
    mutationFn: async (form: AddPaymentMethodForm) => {
      if (form.type === 'CREDIT_CARD') {
        // Client-side tokenisation for cards (AC #1, #2)
        const { token, last4 } = tokenizeCard(form.identifier);
        const display_label = `•••• ${last4}`;
        const response = await addPaymentMethod({ type: form.type, token, display_label });
        return response;
      }
      // Non-card methods: store identifier as-is (AC #4)
      const display_label = form.identifier; // In real app, might mask/label differently
      const response = await addPaymentMethod({ type: form.type, token: form.identifier, display_label });
      return response;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payment-methods'] });
      setForm({ type: 'CREDIT_CARD', identifier: '' });
    },
  });

  const setDefaultMutation = useMutation({
    mutationFn: async (id: string) => {
      const response = await setDefaultPaymentMethod(id);
      return response;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payment-methods'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      await deletePaymentMethod(id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payment-methods'] });
    },
  });

  // Local form state
  const [form, setForm] = useState<AddPaymentMethodForm>({
    type: 'CREDIT_CARD',
    identifier: '',
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.identifier.trim()) return;
    addMutation.mutate(form);
  };

  const paymentMethods = paymentMethodsData?.data ?? [];

  if (isLoading) {
    return (
      <main className="px-4 py-10">
        <div className="mx-auto max-w-3xl">
          <h1 className="text-2xl font-bold text-neutral-900">Payment Methods</h1>
          <p className="mt-2 text-sm text-neutral-500">Loading your saved payment methods...</p>
        </div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="px-4 py-10">
        <div className="mx-auto max-w-3xl">
          <h1 className="text-2xl font-bold text-neutral-900">Payment Methods</h1>
          <p className="mt-2 text-sm text-red-600">Failed to load payment methods. Please try again.</p>
        </div>
      </main>
    );
  }

  return (
    <main className="px-4 py-10">
      <div className="mx-auto max-w-3xl">
        <h1 className="text-2xl font-bold text-neutral-900">Payment Methods</h1>
        <p className="mt-2 text-sm text-neutral-500">
          Manage your saved payment methods for quick recharge.
        </p>

        {/* Add new payment method form */}
        <Card className="mt-6 p-6">
          <h2 className="text-lg font-semibold text-neutral-900">Add Payment Method</h2>
          <form onSubmit={handleSubmit} className="mt-4 space-y-4">
            <div>
              <label htmlFor="type" className="block text-sm font-medium text-neutral-700">
                Type
              </label>
              <select
                id="type"
                value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value as PaymentMethodType })}
                className="mt-1 block w-full rounded-md border-neutral-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-neutral-500 focus:outline-none focus:ring-1 focus:ring-neutral-500"
              >
                {Object.entries(PAYMENT_METHOD_CONFIG).map(([value, { label }]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="identifier" className="block text-sm font-medium text-neutral-700">
                {form.type === 'CREDIT_CARD' ? 'Card Number' : 'Identifier'}
              </label>
              <input
                type={form.type === 'CREDIT_CARD' ? 'text' : 'text'}
                id="identifier"
                value={form.identifier}
                onChange={(e) => setForm({ ...form, identifier: e.target.value })}
                placeholder={
                  form.type === 'CREDIT_CARD'
                    ? '1234 5678 9012 3456'
                    : form.type === 'UPI'
                      ? 'user@upi'
                      : form.type === 'NET_BANKING'
                        ? 'Bank Name'
                        : 'Wallet Handle'
                }
                className="mt-1 block w-full rounded-md border-neutral-300 px-3 py-2 text-sm shadow-sm focus:border-neutral-500 focus:outline-none focus:ring-1 focus:ring-neutral-500"
              />
              {form.type === 'CREDIT_CARD' && (
                <p className="mt-1 text-xs text-neutral-500">
                  Card number is tokenised securely before saving.
                </p>
              )}
            </div>

            <Button
              type="submit"
              disabled={addMutation.isPending || !form.identifier.trim()}
              className="w-full"
            >
              {addMutation.isPending ? 'Adding...' : 'Add Payment Method'}
            </Button>

            {addMutation.error && (
              <p className="text-sm text-red-600">
                Failed to add payment method. Please try again.
              </p>
            )}
          </form>
        </Card>

        {/* List of saved payment methods */}
        <div className="mt-8">
          <h2 className="text-lg font-semibold text-neutral-900">Saved Payment Methods</h2>
          {paymentMethods.length === 0 ? (
            <p className="mt-4 text-sm text-neutral-500">No payment methods saved yet.</p>
          ) : (
            <div className="mt-4 space-y-3">
              {paymentMethods.map((method) => {
                return (
                  <Card key={method.id} className="flex items-center justify-between p-4">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl" aria-hidden="true">
                        {PAYMENT_METHOD_CONFIG[method.type].icon}
                      </span>
                      <div>
                        <p className="font-medium text-neutral-900">{method.display_label}</p>
                        <p className="text-xs text-neutral-500">
                          {PAYMENT_METHOD_CONFIG[method.type].label}
                          {method.is_default && (
                            <span className="ml-2 font-medium text-brand-primary">
                              (Default)
                            </span>
                          )}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {!method.is_default && (
                        <Button
                          variant="secondary"
                          onClick={() => setDefaultMutation.mutate(method.id)}
                          disabled={setDefaultMutation.isPending}
                        >
                          Set Default
                        </Button>
                      )}
                      <Button
                        variant="secondary"
                        onClick={() => deleteMutation.mutate(method.id)}
                        disabled={deleteMutation.isPending}
                        className="text-red-600 hover:bg-red-50"
                      >
                        🗑️
                      </Button>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
