import { useState, useRef } from 'react';
import { useLanguage } from '../context/LanguageContext';
import { api } from '../api/client';

export default function AskVittSetu() {
  const { t, lang } = useLanguage();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);

  async function send(text) {
    const question = text ?? input;
    if (!question.trim()) return;
    const nextMessages = [...messages, { sender: 'user', text: question }];
    setMessages(nextMessages);
    setInput('');
    setLoading(true);
    try {
      const res = await api.ask({ question, history: nextMessages, language: lang });
      setMessages((m) => [...m, { sender: 'bot', text: res.answer }]);
    } catch (err) {
      setMessages((m) => [...m, { sender: 'bot', text: `⚠️ ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  }

  async function toggleRecording() {
    if (recording) {
      mediaRecorderRef.current?.stop();
      setRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((tr) => tr.stop());
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        const form = new FormData();
        form.append('audio', blob, 'recording.webm');
        try {
          const res = await fetch('/transcribe', { method: 'POST', body: form });
          if (res.ok) {
            const data = await res.json();
            if (data.text) send(data.text);
          }
        } catch {
          // voice service unavailable — degrade silently, text chat still works
        }
      };
      recorder.start();
      mediaRecorderRef.current = recorder;
      setRecording(true);
    } catch {
      setRecording(false);
    }
  }

  return (
    <div className="card">
      <h2>{t('nav_ask')}</h2>
      <div className="chat-log">
        {messages.map((m, i) => (
          <div key={i} className={`chat-bubble ${m.sender === 'user' ? 'user' : 'bot'}`}>{m.text}</div>
        ))}
        {loading && <div className="chat-bubble bot">…</div>}
      </div>
      <div className="chat-input-row">
        <textarea
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder="Ask about NSFDC schemes, eligibility, documents..."
        />
        <button className="btn btn-secondary" onClick={toggleRecording} title="Voice input">
          {recording ? '⏹' : '🎙'}
        </button>
        <button className="btn btn-primary" onClick={() => send()} disabled={loading}>➤</button>
      </div>
    </div>
  );
}
