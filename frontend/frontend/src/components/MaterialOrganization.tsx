import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { qualityStatusConfig } from '../data/legalStandards';
import type { RawMaterial, Exhibit, ExhibitSection, QualityStatus } from '../types';

// Empty data - will be fetched from backend in production
const rawMaterials: RawMaterial[] = [];
const exhibits: Exhibit[] = [];
const exhibitSections: ExhibitSection[] = [];

// Helper functions for empty data
const getSectionsByExhibitId = (exhibitId: string): ExhibitSection[] => {
  return exhibitSections.filter(s => s.exhibitId === exhibitId).sort((a, b) => a.order - b.order);
};

const getMaterialsBySectionId = (sectionId: string): RawMaterial[] => {
  const section = exhibitSections.find(s => s.id === sectionId);
  if (!section) return [];
  return rawMaterials.filter(m => section.sourceMaterialIds.includes(m.id));
};

// Icons
const DocumentIcon = () => (
  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
  </svg>
);

const ChevronIcon = ({ expanded }: { expanded: boolean }) => (
  <svg className={`w-4 h-4 transition-transform ${expanded ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
  </svg>
);

const PlusIcon = () => (
  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
  </svg>
);

const UploadIcon = () => (
  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
  </svg>
);

const SparkleIcon = () => (
  <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
    <path d="M12 2L9.19 8.63L2 9.24L7.46 13.97L5.82 21L12 17.27L18.18 21L16.54 13.97L22 9.24L14.81 8.63L12 2Z" />
  </svg>
);

const FolderIcon = ({ open }: { open: boolean }) => (
  <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
    {open ? (
      <path d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h6l2 2h6a2 2 0 012 2v1H3.5a.5.5 0 00-.5.5V18a2 2 0 002 2z" />
    ) : (
      <path d="M10 4H4a2 2 0 00-2 2v12a2 2 0 002 2h16a2 2 0 002-2V8a2 2 0 00-2-2h-8l-2-2z" />
    )}
  </svg>
);

// Filter options for materials
type FilterOption = 'all' | QualityStatus;

interface MaterialCardProps {
  material: RawMaterial;
  isSelected: boolean;
  onClick: () => void;
  onDragStart: (e: React.DragEvent) => void;
}

function MaterialCard({ material, isSelected, onClick, onDragStart }: MaterialCardProps) {
  const { t } = useTranslation();
  const statusConfig = qualityStatusConfig[material.qualityStatus];

  return (
    <div
      draggable={material.qualityStatus === 'approved' || material.qualityStatus === 'needs_review'}
      onDragStart={onDragStart}
      onClick={onClick}
      className={`
        p-3 rounded-lg border-2 cursor-pointer transition-all
        ${isSelected
          ? 'border-slate-900 bg-slate-50 shadow-md'
          : 'border-slate-200 bg-white hover:border-slate-300 hover:shadow-sm'
        }
        ${(material.qualityStatus === 'approved' || material.qualityStatus === 'needs_review') ? 'cursor-grab active:cursor-grabbing' : ''}
        ${material.qualityStatus === 'rejected' ? 'opacity-50' : ''}
      `}
    >
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 text-slate-400">
          <DocumentIcon />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-slate-900 truncate">{material.name}</p>
          <p className="text-xs text-slate-500 mt-0.5">{t('materials.pages', { count: material.pageCount })}</p>

          {/* Status badge */}
          <div className="flex items-center gap-2 mt-2">
            <span
              className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
              style={{ backgroundColor: statusConfig.bgColor, color: statusConfig.color }}
            >
              {t(`materials.qualityStatus.${material.qualityStatus === 'needs_review' ? 'needsReview' : material.qualityStatus}`)}
            </span>
            {material.qualityScore && (
              <span className="text-xs text-slate-500">
                {t('materials.score', { score: material.qualityScore })}
              </span>
            )}
          </div>

          {/* AI suggestion */}
          {material.suggestedExhibit && !material.exhibitId && (
            <div className="flex items-center gap-1 mt-2 text-xs text-purple-600">
              <SparkleIcon />
              <span>{t('materials.suggestedExhibit', { exhibit: material.suggestedExhibit })}</span>
            </div>
          )}

          {/* Quality notes */}
          {material.qualityNotes && (
            <p className="text-xs text-amber-600 mt-1 line-clamp-2">{material.qualityNotes}</p>
          )}
        </div>
      </div>
    </div>
  );
}

// Section card - displays as a folder with materials inside
interface SectionCardProps {
  section: ExhibitSection;
  isExpanded: boolean;
  onToggle: () => void;
  exhibitColor: string;
}

function SectionCard({ section, isExpanded, onToggle, exhibitColor }: SectionCardProps) {
  const { t } = useTranslation();
  const materials = getMaterialsBySectionId(section.id);

  return (
    <div className="rounded-lg border border-slate-200 overflow-hidden bg-white">
      {/* Section header - clickable to expand */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 p-3 text-left hover:bg-slate-50 transition-colors"
      >
        <ChevronIcon expanded={isExpanded} />
        <div className="text-amber-500">
          <FolderIcon open={isExpanded} />
        </div>
        <div
          className="w-7 h-7 rounded-md flex items-center justify-center text-xs font-bold text-white"
          style={{ backgroundColor: exhibitColor }}
        >
          {section.label}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-slate-900">{section.title}</p>
          <p className="text-xs text-slate-500">
            {t('materials.pageRange', { start: section.startPage, end: section.endPage })} · {t('materials.materialCount', { count: materials.length })}
          </p>
        </div>
      </button>

      {/* Materials inside section */}
      {isExpanded && (
        <div className="border-t border-slate-100 bg-slate-50 p-3 space-y-2">
          {materials.length > 0 ? (
            materials.map(material => (
              <div
                key={material.id}
                className="flex items-center gap-2 p-2 rounded-md bg-white border border-slate-200"
              >
                <div className="text-slate-400">
                  <DocumentIcon />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-slate-700 truncate">{material.name}</p>
                  <p className="text-xs text-slate-400">{t('materials.pages', { count: material.pageCount })}</p>
                </div>
              </div>
            ))
          ) : (
            <div className="text-center py-3 text-slate-400 text-xs">
              {t('materials.noMaterials')}
            </div>
          )}
          {/* Add material to section button */}
          <button className="w-full flex items-center justify-center gap-1 p-2 rounded-md border border-dashed border-slate-300 text-slate-400 hover:border-slate-400 hover:text-slate-500 text-xs transition-colors">
            <PlusIcon />
            <span>{t('materials.addMaterialToSection')}</span>
          </button>
        </div>
      )}
    </div>
  );
}

interface ExhibitCardProps {
  exhibit: Exhibit;
  sections: ExhibitSection[];
  isExpanded: boolean;
  onToggle: () => void;
  onDrop: (e: React.DragEvent) => void;
  isDragOver: boolean;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  expandedSections: Set<string>;
  onToggleSection: (sectionId: string) => void;
}

function ExhibitCard({ exhibit, sections, isExpanded, onToggle, onDrop, isDragOver, onDragOver, onDragLeave, expandedSections, onToggleSection }: ExhibitCardProps) {
  const { t } = useTranslation();
  return (
    <div
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      className={`
        rounded-xl border-2 overflow-hidden transition-all
        ${isDragOver ? 'border-dashed scale-[1.02] shadow-md' : 'border-solid'}
      `}
      style={{
        borderColor: isDragOver ? exhibit.color : `${exhibit.color}40`,
        backgroundColor: isDragOver ? `${exhibit.color}08` : 'white'
      }}
    >
      {/* Header */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 p-4 text-left hover:bg-slate-50 transition-colors"
      >
        <ChevronIcon expanded={isExpanded} />
        <div
          className="w-3 h-3 rounded-full flex-shrink-0"
          style={{ backgroundColor: exhibit.color }}
        />
        <div className="flex-1">
          <span className="font-semibold text-slate-900">{exhibit.name}</span>
          <span className="text-slate-500 ml-2">{exhibit.title}</span>
        </div>
        <span className="text-xs text-slate-500 bg-slate-100 px-2 py-1 rounded">
          {t('materials.pages', { count: exhibit.totalPageCount })}
        </span>
      </button>

      {/* Sections (expanded) - now showing as folders */}
      {isExpanded && (
        <div className="px-4 pb-4 space-y-2">
          {sections.length > 0 ? (
            sections.map(section => (
              <SectionCard
                key={section.id}
                section={section}
                isExpanded={expandedSections.has(section.id)}
                onToggle={() => onToggleSection(section.id)}
                exhibitColor={exhibit.color}
              />
            ))
          ) : (
            <div className="text-center py-6 text-slate-400 text-sm">
              {t('materials.dragHint')}
            </div>
          )}

          {/* Add section button */}
          <button className="w-full flex items-center justify-center gap-2 p-2 rounded-lg border-2 border-dashed border-slate-200 text-slate-500 hover:border-slate-300 hover:text-slate-600 transition-colors">
            <PlusIcon />
            <span className="text-sm">{t('materials.addSection')}</span>
          </button>
        </div>
      )}

      {/* Drop zone indicator */}
      {isDragOver && (
        <div
          className="mx-4 mb-4 py-3 rounded-lg border-2 border-dashed text-center text-sm font-medium"
          style={{ borderColor: exhibit.color, color: exhibit.color }}
        >
          {t('materials.dropToAdd', { exhibit: exhibit.name })}
        </div>
      )}
    </div>
  );
}

export function MaterialOrganization() {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<FilterOption>('all');
  const [selectedMaterialId, setSelectedMaterialId] = useState<string | null>(null);
  const [expandedExhibits, setExpandedExhibits] = useState<Set<string>>(new Set(['exhibit-a', 'exhibit-b']));
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['sec-a2'])); // Default expand one section
  const [dragOverExhibitId, setDragOverExhibitId] = useState<string | null>(null);

  // Filter materials
  const filteredMaterials = rawMaterials.filter(m => {
    if (filter === 'all') return !m.exhibitId; // Show unassigned materials
    return m.qualityStatus === filter && !m.exhibitId;
  });

  const handleToggleExhibit = (exhibitId: string) => {
    setExpandedExhibits(prev => {
      const next = new Set(prev);
      if (next.has(exhibitId)) {
        next.delete(exhibitId);
      } else {
        next.add(exhibitId);
      }
      return next;
    });
  };

  const handleToggleSection = (sectionId: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(sectionId)) {
        next.delete(sectionId);
      } else {
        next.add(sectionId);
      }
      return next;
    });
  };

  const handleDragStart = (e: React.DragEvent, materialId: string) => {
    e.dataTransfer.setData('materialId', materialId);
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleDragOver = (e: React.DragEvent, exhibitId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverExhibitId(exhibitId);
  };

  const handleDragLeave = () => {
    setDragOverExhibitId(null);
  };

  const handleDrop = (e: React.DragEvent, exhibitId: string) => {
    e.preventDefault();
    setDragOverExhibitId(null);
    const materialId = e.dataTransfer.getData('materialId');
    if (materialId) {
      // In real app, this would update state
      console.log(`Move material ${materialId} to exhibit ${exhibitId}`);
    }
  };

  const selectedMaterial = selectedMaterialId
    ? rawMaterials.find(m => m.id === selectedMaterialId)
    : null;

  return (
    <div className="flex flex-col h-screen bg-slate-100">
      {/* Header */}
      <div className="flex-shrink-0 px-6 py-4 bg-white border-b border-slate-200">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">{t('materials.title')}</h1>
            <p className="text-sm text-slate-500 mt-1">{t('materials.subtitle')}</p>
          </div>
          <button className="flex items-center gap-2 px-4 py-2 bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition-colors">
            <UploadIcon />
            <span>{t('materials.uploadMaterials')}</span>
          </button>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Material Pool */}
        <div className="w-[340px] flex-shrink-0 border-r border-slate-200 bg-white flex flex-col">
          {/* Filter */}
          <div className="flex-shrink-0 px-4 py-3 border-b border-slate-200">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-900">{t('materials.rawMaterials')}</h2>
              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value as FilterOption)}
                className="text-xs border border-slate-200 rounded-lg px-2 py-1 bg-white"
              >
                <option value="all">{t('materials.filterOptions.unassigned')}</option>
                <option value="pending">{t('materials.filterOptions.pending')}</option>
                <option value="approved">{t('materials.filterOptions.approved')}</option>
                <option value="needs_review">{t('materials.filterOptions.needsReview')}</option>
                <option value="rejected">{t('materials.filterOptions.rejected')}</option>
              </select>
            </div>
            <p className="text-xs text-slate-500 mt-1">
              {t('materials.materialCount', { count: filteredMaterials.length })}
            </p>
          </div>

          {/* Material list */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {filteredMaterials.map(material => (
              <MaterialCard
                key={material.id}
                material={material}
                isSelected={selectedMaterialId === material.id}
                onClick={() => setSelectedMaterialId(material.id)}
                onDragStart={(e) => handleDragStart(e, material.id)}
              />
            ))}
            {filteredMaterials.length === 0 && (
              <div className="text-center py-8 text-slate-400">
                <p>{t('materials.noMatchingMaterials')}</p>
              </div>
            )}
          </div>
        </div>

        {/* Right: Exhibits */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Exhibit list */}
          <div className="flex-1 overflow-y-auto p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-slate-900">{t('materials.exhibits')}</h2>
              <span className="text-xs text-slate-500">{t('materials.exhibitCount', { count: exhibits.length })}</span>
            </div>
            <div className="space-y-4">
              {exhibits.map(exhibit => (
                <ExhibitCard
                  key={exhibit.id}
                  exhibit={exhibit}
                  sections={getSectionsByExhibitId(exhibit.id)}
                  isExpanded={expandedExhibits.has(exhibit.id)}
                  onToggle={() => handleToggleExhibit(exhibit.id)}
                  onDrop={(e) => handleDrop(e, exhibit.id)}
                  isDragOver={dragOverExhibitId === exhibit.id}
                  onDragOver={(e) => handleDragOver(e, exhibit.id)}
                  onDragLeave={handleDragLeave}
                  expandedSections={expandedSections}
                  onToggleSection={handleToggleSection}
                />
              ))}

              {/* Add new exhibit button */}
              <button className="w-full flex items-center justify-center gap-2 p-4 rounded-xl border-2 border-dashed border-slate-300 text-slate-500 hover:border-slate-400 hover:text-slate-600 transition-colors">
                <PlusIcon />
                <span>{t('materials.newExhibit')}</span>
              </button>
            </div>
          </div>

          {/* Preview area */}
          <div className="flex-shrink-0 h-[200px] border-t border-slate-200 bg-white">
            {selectedMaterial ? (
              <div className="h-full p-4">
                <div className="h-full rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center">
                  <div className="text-center">
                    <DocumentIcon />
                    <p className="text-sm font-medium text-slate-700 mt-2">{selectedMaterial.name}</p>
                    <p className="text-xs text-slate-500">{t('materials.pages', { count: selectedMaterial.pageCount })}</p>
                    <p className="text-xs text-slate-400 mt-2">{t('materials.previewArea')}</p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="h-full flex items-center justify-center text-slate-400">
                <p className="text-sm">{t('materials.clickToPreview')}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
