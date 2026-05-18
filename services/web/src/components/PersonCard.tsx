import { useState } from 'react';
import type { PersonResponse } from '../types/api';
import { useDeletePerson, useRematchPerson } from '../api/persons';
import EnrollmentDropzone from './EnrollmentDropzone';

interface Props {
  person: PersonResponse;
}

export default function PersonCard({ person }: Props) {
  const [showDropzone,   setShowDropzone]   = useState(false);
  const [confirmDelete,  setConfirmDelete]  = useState(false);
  const [rematchResult,  setRematchResult]  = useState<number | null>(null);

  const deletePerson  = useDeletePerson();
  const rematchPerson = useRematchPerson();

  async function handleDelete() {
    await deletePerson.mutateAsync(person.id);
    // Parent list re-fetches via queryClient.invalidateQueries in the hook
  }

  async function handleRematch() {
    const result = await rematchPerson.mutateAsync(person.id);
    setRematchResult(result.matched);
    setTimeout(() => setRematchResult(null), 4000);
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold text-gray-900">{person.name}</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            {person.enrollment_count} enrollment{person.enrollment_count !== 1 ? 's' : ''}
            {person.enrollment_count < 5 && (
              <span className="ml-1 text-amber-600">(⚠ fewer than 5 — accuracy reduced)</span>
            )}
          </p>
        </div>
        <div className="text-2xl select-none">👤</div>
      </div>

      {/* Actions */}
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={() => { setShowDropzone(v => !v); setConfirmDelete(false); }}
          className="text-xs font-medium text-blue-600 hover:text-blue-800 border border-blue-200 rounded px-2 py-1 transition-colors"
        >
          {showDropzone ? 'Cancel' : '+ Add photos'}
        </button>

        <button
          onClick={handleRematch}
          disabled={rematchPerson.isPending}
          className="text-xs font-medium text-gray-600 hover:text-gray-800 border border-gray-200 rounded px-2 py-1 disabled:opacity-50 transition-colors"
        >
          {rematchPerson.isPending ? 'Rematching…' : '🔄 Rematch'}
        </button>

        {!confirmDelete ? (
          <button
            onClick={() => setConfirmDelete(true)}
            className="text-xs font-medium text-red-500 hover:text-red-700 border border-red-200 rounded px-2 py-1 transition-colors ml-auto"
          >
            Delete
          </button>
        ) : (
          <div className="flex gap-1 ml-auto items-center">
            <span className="text-xs text-gray-600">Sure?</span>
            <button
              onClick={handleDelete}
              disabled={deletePerson.isPending}
              className="text-xs font-medium text-red-600 hover:text-red-800 border border-red-300 rounded px-2 py-1 disabled:opacity-50"
            >
              {deletePerson.isPending ? 'Deleting…' : 'Yes, delete'}
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="text-xs text-gray-500 hover:text-gray-700 border border-gray-200 rounded px-2 py-1"
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      {/* Rematch result */}
      {rematchResult !== null && (
        <div className="text-xs text-green-700 bg-green-50 border border-green-200 rounded px-2 py-1">
          ✓ Updated {rematchResult} face match{rematchResult !== 1 ? 'es' : ''}
        </div>
      )}

      {/* Enrollment dropzone (expanded inline) */}
      {showDropzone && (
        <div className="pt-1 border-t border-gray-100">
          <EnrollmentDropzone
            personId={person.id}
            onSuccess={(_n) => {
              setShowDropzone(false);
              // The hook's onSuccess invalidates ['persons'] — card will re-render with updated count
            }}
          />
        </div>
      )}
    </div>
  );
}
