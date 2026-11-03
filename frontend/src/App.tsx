import { useState } from 'react';
import Upload from './Upload';
import Projects from './Projects';
export default function App() {
  const [view, setView] = useState<'upload' | 'projects'>('upload');
  const [projectsOpened, setProjectsOpened] = useState(false);
  return <><nav aria-label="Разделы приложения"><button aria-pressed={view === 'upload'} onClick={() => setView('upload')}>Извлечение текста</button><button aria-pressed={view === 'projects'} onClick={() => { setProjectsOpened(true); setView('projects'); }}>Проекты</button></nav>
    <div hidden={view !== 'upload'}><Upload /></div>
    {projectsOpened && <div hidden={view !== 'projects'}><Projects /></div>}</>;
}
