import { useState } from 'react';
import clsx from 'clsx';
import { useSettings } from '../context/SettingsContext';
import { addToast } from '../hooks/useToast';

type TestResult = 'idle' | 'testing' | 'ok' | 'auth-fail' | 'error';

export default function SettingsPage() {
  const { settings, saveSettings } = useSettings();

  const [tokenInput,   setTokenInput]   = useState(settings.apiToken);
  const [apiUrlInput,  setApiUrlInput]  = useState(settings.apiBaseUrl);
  const [showToken,    setShowToken]    = useState(false);
  const [saved,        setSaved]        = useState(false);
  const [testResult,   setTestResult]   = useState<TestResult>('idle');
  const [testDetail,   setTestDetail]   = useState('');

  function handleSave() {
    saveSettings({ apiToken: tokenInput.trim(), apiBaseUrl: apiUrlInput.trim() });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
    addToast('Settings saved', 'success');
  }

  async function handleTest() {
    setTestResult('testing');
    setTestDetail('');

    const prefix = apiUrlInput.trim() || '/api';

    try {
      // Step 1: health check (no auth)
      const health = await fetch(`${prefix}/health`);
      if (!health.ok) {
        setTestResult('error');
        setTestDetail(`Health check failed: ${health.status}`);
        return;
      }

      // Step 2: persons endpoint (with token)
      const token = tokenInput.trim();
      if (!token) {
        setTestResult('auth-fail');
        setTestDetail('No token provided. Enter a token and try again.');
        return;
      }

      const persons = await fetch(`${prefix}/persons`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (persons.status === 401 || persons.status === 403) {
        setTestResult('auth-fail');
        setTestDetail(`Token rejected (${persons.status}). Check API_TOKEN env var on the server.`);
        return;
      }

      if (!persons.ok) {
        setTestResult('error');
        setTestDetail(`Persons request failed: ${persons.status}`);
        return;
      }

      setTestResult('ok');
      setTestDetail('API reachable · Token valid');
    } catch (err) {
      setTestResult('error');
      setTestDetail(err instanceof Error ? err.message : 'Network error');
    }
  }

  const testBadge = {
    idle:       { label: 'Test Connection', classes: 'bg-gray-100 text-gray-700 hover:bg-gray-200' },
    testing:    { label: 'Testing…',        classes: 'bg-gray-100 text-gray-400 cursor-wait' },
    ok:         { label: '✓ Connected',     classes: 'bg-green-100 text-green-700' },
    'auth-fail':{ label: '✕ Auth failed',   classes: 'bg-red-100 text-red-700' },
    error:      { label: '✕ Error',         classes: 'bg-red-100 text-red-700' },
  }[testResult];

  return (
    <div className="p-4 md:p-6 max-w-lg">
      <h1 className="text-lg font-semibold text-gray-900 mb-6">Settings</h1>

      <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm space-y-5">

        {/* API Token */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">
            API Token
          </label>
          <div className="flex gap-2">
            <input
              type={showToken ? 'text' : 'password'}
              value={tokenInput}
              onChange={e => { setTokenInput(e.target.value); setTestResult('idle'); }}
              placeholder="Enter API_TOKEN from .env"
              className="flex-1 text-sm border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
              autoComplete="current-password"
            />
            <button
              onClick={() => setShowToken(v => !v)}
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-500 hover:text-gray-700 hover:bg-gray-50"
              aria-label={showToken ? 'Hide token' : 'Show token'}
            >
              {showToken ? '🙈' : '👁'}
            </button>
          </div>
          <p className="mt-1.5 text-xs text-gray-400">
            Bearer token from the <code className="font-mono">API_TOKEN</code> env var in your <code className="font-mono">.env</code> file.
            Stored in browser localStorage.
          </p>
        </div>

        {/* API Base URL (advanced) */}
        <details className="group">
          <summary className="text-sm font-medium text-gray-600 cursor-pointer hover:text-gray-800 select-none">
            Advanced: API Base URL
          </summary>
          <div className="mt-2">
            <input
              type="url"
              value={apiUrlInput}
              onChange={e => setApiUrlInput(e.target.value)}
              placeholder="Leave blank to use nginx /api/ proxy"
              className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">
              Default: blank (uses nginx proxy at <code className="font-mono">/api/</code>).
              Override only if accessing the API directly, e.g. <code className="font-mono">http://192.168.1.10:8000</code>.
            </p>
          </div>
        </details>

        {/* Save + Test buttons */}
        <div className="flex items-center gap-3 pt-1">
          <button
            onClick={handleSave}
            className={clsx(
              'px-4 py-2 text-sm font-medium rounded-lg transition-colors',
              saved
                ? 'bg-green-600 text-white'
                : 'bg-blue-600 text-white hover:bg-blue-700',
            )}
          >
            {saved ? '✓ Saved' : 'Save'}
          </button>

          <button
            onClick={handleTest}
            disabled={testResult === 'testing'}
            className={clsx(
              'px-4 py-2 text-sm font-medium rounded-lg transition-colors',
              testBadge.classes,
            )}
          >
            {testBadge.label}
          </button>
        </div>

        {/* Test result detail */}
        {testDetail && (
          <p className={clsx(
            'text-xs mt-1',
            testResult === 'ok' ? 'text-green-700' : 'text-red-600',
          )}>
            {testDetail}
          </p>
        )}

      </div>

      {/* How-to info */}
      <div className="mt-5 bg-gray-50 border border-gray-200 rounded-lg p-4 text-xs text-gray-600 space-y-1.5">
        <p className="font-medium text-gray-700">Setup instructions</p>
        <ol className="list-decimal list-inside space-y-1">
          <li>Copy your <code className="font-mono">API_TOKEN</code> value from the server's <code className="font-mono">.env</code> file.</li>
          <li>Paste it into the API Token field above and click Save.</li>
          <li>Click Test Connection — both checks should show ✓.</li>
          <li>Navigate to Search or People to start using the app.</li>
        </ol>
      </div>
    </div>
  );
}
