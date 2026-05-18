import { useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { usePersons, useCreatePerson } from '../api/persons';
import { useSettings } from '../context/SettingsContext';
import PersonCard from '../components/PersonCard';
import type { PersonResponse } from '../types/api';

export default function PeoplePage() {
  const { settings }        = useSettings();
  const [name, setName]     = useState('');
  const [addError, setAddError] = useState<string | null>(null);
  const inputRef            = useRef<HTMLInputElement>(null);

  const queryClient = useQueryClient();
  const { data: persons = [], isLoading, isError, error } = usePersons();
  const createPerson = useCreatePerson();

  // No-token banner
  if (!settings.apiToken) {
    return (
      <div className="p-6">
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800">
          API token not configured.{' '}
          <Link to="/settings" className="font-medium underline">Go to Settings →</Link>
        </div>
      </div>
    );
  }

  async function handleAddPerson(e: React.FormEvent) {
    e.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) return;

    setAddError(null);

    // Snapshot for rollback
    const previousPersons = queryClient.getQueryData<PersonResponse[]>(['persons']);

    // Optimistic: prepend temporary card
    const tempPerson: PersonResponse = {
      id:               `temp-${Date.now()}`,
      name:             trimmedName,
      notes:            null,
      created_at:       new Date().toISOString(),
      enrollment_count: 0,
    };
    queryClient.setQueryData<PersonResponse[]>(
      ['persons'],
      (old = []) => [tempPerson, ...old],
    );
    setName('');

    try {
      await createPerson.mutateAsync(trimmedName);
      // Hook's onSuccess calls invalidateQueries(['persons']) → re-fetch replaces optimistic card
    } catch (err) {
      // Rollback
      queryClient.setQueryData(['persons'], previousPersons);
      setAddError(err instanceof Error ? err.message : 'Failed to create person');
      setName(trimmedName);
      inputRef.current?.focus();
    }
  }

  return (
    <div className="p-4 md:p-6">
      <h1 className="text-lg font-semibold text-gray-900 mb-5">People</h1>

      {/* Add person form */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 mb-6 shadow-sm max-w-md">
        <h2 className="text-sm font-medium text-gray-700 mb-3">Add new person</h2>
        <form onSubmit={handleAddPerson} className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={name}
            onChange={e => { setName(e.target.value); setAddError(null); }}
            placeholder="Name (e.g. Alice)"
            maxLength={100}
            required
            className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={createPerson.isPending || !name.trim()}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
          >
            {createPerson.isPending ? 'Adding…' : 'Add'}
          </button>
        </form>
        {addError && (
          <p className="mt-2 text-xs text-red-600">{addError}</p>
        )}
        <p className="mt-2 text-xs text-gray-400">
          After creating a person, drag their reference photos onto the card to enroll them.
          5+ images recommended for best recognition accuracy.
        </p>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-32 bg-gray-200 rounded-xl animate-pulse" />
          ))}
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          Failed to load persons: {error instanceof Error ? error.message : 'Unknown error'}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !isError && persons.length === 0 && (
        <div className="flex flex-col items-center py-20 text-gray-400">
          <span className="text-4xl mb-3">👤</span>
          <p className="text-sm">No persons enrolled yet</p>
          <p className="text-xs mt-1">Use the form above to add your first person</p>
        </div>
      )}

      {/* Person grid */}
      {persons.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {persons.map(person => (
            <PersonCard key={person.id} person={person} />
          ))}
        </div>
      )}
    </div>
  );
}
