import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AppProvider, useApp } from './context/AppContext';
import {
  Header,
  DocumentViewer,
  EvidenceCardPool,
  ConnectionLines,
  ViewModeSwitcher,
  SankeyView,
  MaterialOrganization,
  WritingCanvas,
  LanguageSwitcher,
  ArgumentAssembly,
} from './components';

type PageType = 'mapping' | 'materials' | 'writing';

function AppContent() {
  const { viewMode } = useApp();
  const [currentPage, setCurrentPage] = useState<PageType>('mapping');
  const { t } = useTranslation();

  // Render the appropriate view based on viewMode
  const renderMappingView = () => {
    switch (viewMode) {
      case 'sankey':
        return (
          <div className="flex-1 overflow-hidden bg-white relative">
            <SankeyView />
          </div>
        );
      case 'line':
      default:
        return (
          <>
            {/* Panel 2: Evidence Cards (40%) */}
            <div className="w-[40%] flex-shrink-0 border-r border-slate-200 overflow-hidden">
              <EvidenceCardPool />
            </div>

            {/* Panel 3: Argument Assembly (35%) - includes StandardFilterBar */}
            <div className="w-[35%] flex-shrink-0 bg-white overflow-hidden">
              <ArgumentAssembly />
            </div>

            {/* SVG Connection Lines (rendered on top) */}
            <ConnectionLines />
          </>
        );
    }
  };

  // If on materials page, render MaterialOrganization
  if (currentPage === 'materials') {
    return (
      <div className="flex flex-col h-screen">
        {/* Page navigation */}
        <div className="flex-shrink-0 px-4 py-2 bg-slate-900 text-white flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setCurrentPage('mapping')}
              className="text-sm text-slate-400 hover:text-white transition-colors"
            >
              ← {t('nav.backToMapping')}
            </button>
            <span className="text-sm font-medium">{t('nav.materials')}</span>
          </div>
          <LanguageSwitcher />
        </div>
        <div className="flex-1 overflow-hidden">
          <MaterialOrganization />
        </div>
      </div>
    );
  }

  // If on writing page, render WritingCanvas
  if (currentPage === 'writing') {
    return (
      <div className="flex flex-col h-screen">
        {/* Page navigation */}
        <div className="flex-shrink-0 px-4 py-2 bg-slate-900 text-white flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setCurrentPage('mapping')}
              className="text-sm text-slate-400 hover:text-white transition-colors"
            >
              ← {t('nav.backToMapping')}
            </button>
            <span className="text-sm font-medium">{t('nav.writingCanvas')}</span>
          </div>
          <LanguageSwitcher />
        </div>
        <div className="flex-1 overflow-hidden">
          <WritingCanvas />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-slate-100">
      {/* Header */}
      <Header />

      {/* View Mode Switcher + Writing Canvas */}
      <div className="px-4 py-2 bg-white border-b border-slate-200 flex items-center justify-between">
        <ViewModeSwitcher />
        <button
          onClick={() => setCurrentPage('writing')}
          className="text-sm text-white bg-slate-900 hover:bg-slate-800 px-3 py-1.5 rounded-lg transition-colors"
        >
          {t('nav.writingCanvas')}
        </button>
      </div>

      {/* Main content area */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Panel 1: Document Viewer (25%) - z-0 to stay below connection lines */}
        <div className="w-[25%] flex-shrink-0 border-r border-slate-200 bg-white overflow-hidden relative z-0">
          <DocumentViewer />
        </div>

        {/* Right side: changes based on view mode */}
        {renderMappingView()}
      </div>
    </div>
  );
}

function App() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  );
}

export default App;
