import { useTranslation } from 'react-i18next';

interface StandardActionModalProps {
  standardName: string;
  standardColor: string;
  argumentCount: number;
  subArgumentCount: number;
  onConfirm: () => void;
  onCancel: () => void;
  isRemoving: boolean;
}

export default function StandardActionModal({
  standardName,
  standardColor,
  argumentCount,
  subArgumentCount,
  onConfirm,
  onCancel,
  isRemoving,
}: StandardActionModalProps) {
  const { t } = useTranslation();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onCancel}
      />

      {/* Modal card */}
      <div className="relative bg-white rounded-xl shadow-xl w-full max-w-sm mx-4 overflow-hidden">
        {/* Header */}
        <div className="px-5 py-4 border-b border-slate-200 bg-slate-50">
          <div className="flex items-center gap-2">
            {/* Warning icon */}
            <svg className="w-5 h-5 text-red-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            <h3 className="text-sm font-semibold text-slate-800">
              {t('graph.removeStandard.title', 'Remove Standard')}
            </h3>
          </div>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-3">
          {/* Standard tag */}
          <div className="flex items-center gap-2">
            <div
              className="w-3 h-3 rounded-full flex-shrink-0"
              style={{ backgroundColor: standardColor }}
            />
            <span className="text-sm font-medium text-slate-700">{standardName}</span>
          </div>

          {/* Description */}
          <p className="text-sm text-slate-600">
            {t('graph.removeStandard.description', {
              defaultValue: 'This will permanently remove {{argCount}} argument(s) and {{subArgCount}} sub-argument(s) under this standard, along with all associated letter content.',
              argCount: argumentCount,
              subArgCount: subArgumentCount,
            })}
          </p>

          {/* Warning */}
          <p className="text-xs text-red-600 font-medium">
            {t('graph.removeStandard.warning', 'This action cannot be undone.')}
          </p>
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-slate-200 bg-slate-50 flex items-center justify-end gap-3">
          <button
            onClick={onCancel}
            disabled={isRemoving}
            className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 transition-colors disabled:opacity-50"
          >
            {t('common.cancel', 'Cancel')}
          </button>
          <button
            onClick={onConfirm}
            disabled={isRemoving}
            className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:bg-red-400 disabled:cursor-not-allowed transition-colors"
          >
            {isRemoving
              ? t('graph.removeStandard.removing', 'Removing...')
              : t('graph.removeStandard.confirm', 'Remove')
            }
          </button>
        </div>
      </div>
    </div>
  );
}
