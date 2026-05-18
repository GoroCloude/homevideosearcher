import { useSettings } from '../context/SettingsContext';

/** Convenience hook: read/write only the API token. */
export function useApiToken() {
  const { settings, saveSettings } = useSettings();
  return {
    token:    settings.apiToken,
    setToken: (token: string) => saveSettings({ apiToken: token }),
  };
}
