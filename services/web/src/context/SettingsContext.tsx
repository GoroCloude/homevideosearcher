import { createContext, useContext, useState, ReactNode } from 'react';

const LS_TOKEN   = 'hvs:api_token';
const LS_API_URL = 'hvs:api_base_url';

export interface Settings {
  apiBaseUrl: string;   // '' = use nginx /api/ proxy (default)
  apiToken:   string;
}

interface SettingsContextValue {
  settings:     Settings;
  saveSettings: (patch: Partial<Settings>) => void;
}

export const SettingsContext = createContext<SettingsContextValue>({
  settings:     { apiBaseUrl: '', apiToken: '' },
  saveSettings: () => {},
});

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings>(() => ({
    apiBaseUrl: localStorage.getItem(LS_API_URL) ?? '',
    apiToken:   localStorage.getItem(LS_TOKEN)   ?? '',
  }));

  const saveSettings = (patch: Partial<Settings>) => {
    const next = { ...settings, ...patch };
    localStorage.setItem(LS_API_URL, next.apiBaseUrl);
    localStorage.setItem(LS_TOKEN,   next.apiToken);
    setSettings(next);
  };

  return (
    <SettingsContext.Provider value={{ settings, saveSettings }}>
      {children}
    </SettingsContext.Provider>
  );
}

export const useSettings = () => useContext(SettingsContext);
