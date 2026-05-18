import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import SearchPage    from './pages/SearchPage';
import VideosPage    from './pages/VideosPage';
import PeoplePage    from './pages/PeoplePage';
import ClustersPage  from './pages/ClustersPage';
import SettingsPage  from './pages/SettingsPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index           element={<SearchPage />} />
          <Route path="videos"   element={<VideosPage />} />
          <Route path="people"   element={<PeoplePage />} />
          <Route path="clusters" element={<ClustersPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*"        element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
