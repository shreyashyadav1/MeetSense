import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Dashboard } from './pages/Dashboard';
import { MeetingRoom } from './pages/MeetingRoom';
import { MeetingDetails } from './pages/MeetingDetails';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/meeting/:id/live" element={<MeetingRoom />} />
        <Route path="/meeting/:id" element={<MeetingDetails />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
