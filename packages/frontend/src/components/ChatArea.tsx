import { useRef, useEffect } from 'react';
import { useApp } from '../AppContext';
import { formatMarkdown } from '../utils/markdown';
import IndexingProgress from './IndexingProgress';
import InputArea from './InputArea';
import ThinkingOverlay from './ThinkingOverlay';

export default function ChatArea() {
  const { sessions, activeSessionId, chatMode } = useApp();
  const messagesRef = useRef<HTMLDivElement>(null);

  const currentSess = sessions.find(s => s.id === activeSessionId);
  const isEmpty = !currentSess || !currentSess.messages || currentSess.messages.length === 0;

  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
    }
  }, [currentSess?.messages]);



  return (
    <main className="chat-area" id="main-area">
      <div id="chat-interface" className={`chat-interface${isEmpty ? ' empty-chat' : ''}`}>
        <IndexingProgress />

        <div id="messages-scroll-area" className="messages" ref={messagesRef}>
          {!isEmpty && currentSess?.messages.map((msg, i) => (
            <MessageComponent key={i} msg={msg} />
          ))}
          <div id="streaming-messages-container" style={{ display: 'flex', flexDirection: 'column', gap: '20px', width: '100%' }}></div>
        </div>

        <div className="chat-empty-hero" aria-hidden={!isEmpty}>
          <h1>Palimind</h1>
          <p>
            {chatMode === 'document'
              ? <>Ask questions about your indexed files — answers come straight from your documents.</>
              : <>Chat directly with a local LLM on your machine.</>}
            <br />
            Tip: type <strong>@agent</strong> (e.g. <strong>@nova</strong>) to delegate a task to an AI agent.
          </p>
        </div>

        <ThinkingOverlay />
        <InputArea />
      </div>
    </main>
  );
}

function MessageComponent({ msg }: { msg: { role: string; content: string; sources?: string[] } }) {
  const isUser = msg.role === 'user';

  let contentText = '';
  if (msg.sources && msg.sources.length > 0) {
    contentText += `*Sources: ${msg.sources.join(', ')}*\n\n`;
  }
  contentText += msg.content;

  return (
    <div className={`message ${isUser ? 'user-message' : 'system-message'}`}>
      <div className="message-wrapper">
        <div
          className="message-content"
          dangerouslySetInnerHTML={{ __html: formatMarkdown(contentText) }}
        />
      </div>
    </div>
  );
}
