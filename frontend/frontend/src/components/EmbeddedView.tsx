import { useState } from 'react';
import { useApp } from '../context/AppContext';
import { legalStandards } from '../data/legalStandards';
import type { Snippet, LegalStandard, Connection } from '../types';

// Mini snippet card for embedded view
function MiniSnippetCard({
  snippet,
  connection,
  onRemove,
  onConfirm,
}: {
  snippet: Snippet;
  connection: Connection;
  onRemove: () => void;
  onConfirm: () => void;
}) {
  // Use exhibitId from snippet (real data from backend)
  const exhibitName = snippet.exhibitId ? `Exhibit ${snippet.exhibitId}` : snippet.documentId;

  return (
    <div
      className={`
        group flex items-start gap-2 p-2 rounded-md text-xs
        ${connection.isConfirmed
          ? 'bg-slate-50 border border-slate-200'
          : 'bg-amber-50 border border-amber-200 border-dashed'
        }
      `}
    >
      <div
        className="w-2 h-2 rounded-full mt-1 flex-shrink-0"
        style={{ backgroundColor: snippet.color }}
      />
      <div className="flex-1 min-w-0">
        <p className="text-slate-700 line-clamp-2">{snippet.summary}</p>
        <p className="text-slate-400 mt-0.5 truncate">
          {exhibitName}
        </p>
      </div>
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {!connection.isConfirmed && (
          <button
            onClick={(e) => { e.stopPropagation(); onConfirm(); }}
            className="p-1 text-green-600 hover:bg-green-100 rounded"
            title="Confirm mapping"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </button>
        )}
        <button
          onClick={(e) => { e.stopPropagation(); onRemove(); }}
          className="p-1 text-red-500 hover:bg-red-100 rounded"
          title="Remove mapping"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  );
}

// Standard block with embedded snippets
function StandardBlock({
  standard,
  snippets,
  connections,
}: {
  standard: LegalStandard;
  snippets: Snippet[];
  connections: Connection[];
}) {
  const {
    removeConnection,
    confirmConnection,
    addConnection,
    setFocusState,
    focusState,
    isElementHighlighted,
  } = useApp();

  const [isDragOver, setIsDragOver] = useState(false);
  const isHighlighted = isElementHighlighted('standard', standard.id);
  const isFocused = focusState.type === 'standard' && focusState.id === standard.id;

  // Get connected snippets for this standard
  const connectedSnippets = connections
    .filter(c => c.standardId === standard.id)
    .map(conn => ({
      snippet: snippets.find(s => s.id === conn.snippetId)!,
      connection: conn,
    }))
    .filter(item => item.snippet);

  const confirmedCount = connectedSnippets.filter(c => c.connection.isConfirmed).length;
  const suggestedCount = connectedSnippets.length - confirmedCount;

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const snippetId = e.dataTransfer.getData('snippetId');
    if (snippetId) {
      addConnection(snippetId, standard.id, true);
    }
  };

  return (
    <div
      className={`
        rounded-lg border-2 transition-all duration-200
        ${isDragOver
          ? 'border-dashed bg-blue-50'
          : isFocused
            ? 'border-solid shadow-md'
            : 'border-slate-200'
        }
        ${!isHighlighted && focusState.type !== 'none' ? 'opacity-20' : ''}
      `}
      style={{
        borderColor: isDragOver ? '#3b82f6' : isFocused ? standard.color : undefined
      }}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={() => setFocusState({ type: 'standard', id: standard.id })}
    >
      {/* Header */}
      <div
        className="px-3 py-2 border-b flex items-center justify-between cursor-pointer"
        style={{ borderBottomColor: `${standard.color}30` }}
      >
        <div className="flex items-center gap-2">
          <div
            className="w-3 h-3 rounded-full"
            style={{ backgroundColor: standard.color }}
          />
          <span className="font-medium text-sm text-slate-800">{standard.shortName}</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {confirmedCount > 0 && (
            <span className="px-1.5 py-0.5 bg-green-100 text-green-700 rounded">
              {confirmedCount} confirmed
            </span>
          )}
          {suggestedCount > 0 && (
            <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded">
              {suggestedCount} suggested
            </span>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="p-2 space-y-2 min-h-[60px]">
        {connectedSnippets.length === 0 ? (
          <div className="text-xs text-slate-400 text-center py-4">
            {isDragOver ? 'Drop here to connect' : 'Drag snippets here'}
          </div>
        ) : (
          connectedSnippets.map(({ snippet, connection }) => (
            <MiniSnippetCard
              key={connection.id}
              snippet={snippet}
              connection={connection}
              onRemove={() => removeConnection(connection.id)}
              onConfirm={() => confirmConnection(connection.id)}
            />
          ))
        )}
      </div>
    </div>
  );
}

export function EmbeddedView() {
  const { allSnippets, connections } = useApp();

  return (
    <div className="h-full overflow-auto p-4">
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {legalStandards.map(standard => (
          <StandardBlock
            key={standard.id}
            standard={standard}
            snippets={allSnippets}
            connections={connections}
          />
        ))}
      </div>
    </div>
  );
}
