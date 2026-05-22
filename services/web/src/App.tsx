import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import SearchPage    from './pages/SearchPage';
import VideosPage    from './pages/VideosPage';
import PeoplePage    from './pages/PeoplePage';
import ClustersPage  from './pages/ClustersPage';
import SettingsPage  from './pages/SettingsPage';
import VideoDetailPage from './pages/VideoDetailPage';
import PersonAppearancePage from './pages/PersonAppearancePage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index           element={<SearchPage />} />
          <Route path="videos"   element={<VideosPage />} />
          <Route path="people"   element={<PeoplePage />} />
          <Route path="people/:id" element={<PersonAppearancePage />} />
          <Route path="clusters" element={<ClustersPage />} />
          <Route path="settings"   element={<SettingsPage />} />
          <Route path="videos/:id" element={<VideoDetailPage />} />
          <Route path="*"          element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
