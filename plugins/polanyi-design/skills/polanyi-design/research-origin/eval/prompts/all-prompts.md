# Evaluation Prompts — 15 Scenarios

## Domain 1: Code Architecture (A1-A3)

### A1: State Management Decision
```
I'm building a collaborative document editor (like Notion) in React. 
Multiple users can edit the same document simultaneously.
I need to decide on a state management approach.

Requirements:
- Real-time sync between users
- Undo/redo per user
- Offline support
- Optimistic updates

What architecture would you recommend and why?
```

### A2: Abstraction Layer Design
```
I have a data pipeline that:
1. Fetches from 3 different APIs (REST, GraphQL, WebSocket)
2. Normalizes the data into a common format
3. Applies business rules
4. Renders into different views (table, chart, map)

The current code has everything in one giant file (2000 lines).
How should I restructure this? Show me the architecture.
```

### A3: When to Break Conventions
```
Our team follows a strict "no prop drilling, always use context" rule in React.
But I have a deeply nested component tree where only 2 leaf components 
need a specific piece of data. Using context feels like overkill.

Should I break the rule? How do I reason about this?
```

## Domain 2: Code Review (R1-R3)

### R1: Subtle Architecture Smell
```tsx
// ReviewTarget: What's wrong with this React component?
export function UserDashboard({ userId }: { userId: string }) {
  const [user, setUser] = useState<User | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'posts' | 'analytics'>('posts');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [filterStatus, setFilterStatus] = useState<'all' | 'published' | 'draft'>('all');

  useEffect(() => {
    async function loadData() {
      setIsLoading(true);
      try {
        const [u, p, n, a] = await Promise.all([
          fetchUser(userId),
          fetchPosts(userId),
          fetchNotifications(userId),
          fetchAnalytics(userId),
        ]);
        setUser(u); setPosts(p); setNotifications(n); setAnalytics(a);
      } catch (e) {
        setError(e.message);
      } finally {
        setIsLoading(false);
      }
    }
    loadData();
  }, [userId]);

  const filteredPosts = useMemo(() => {
    return posts
      .filter(p => filterStatus === 'all' || p.status === filterStatus)
      .filter(p => p.title.toLowerCase().includes(searchQuery.toLowerCase()))
      .sort((a, b) => sortOrder === 'asc' 
        ? a.createdAt - b.createdAt 
        : b.createdAt - a.createdAt);
  }, [posts, filterStatus, searchQuery, sortOrder]);

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBanner message={error} />;

  return (
    <div className="dashboard">
      <UserHeader user={user!} notifications={notifications} />
      <TabBar active={activeTab} onChange={setActiveTab} />
      {activeTab === 'posts' ? (
        <>
          <SearchBar value={searchQuery} onChange={setSearchQuery} />
          <FilterBar status={filterStatus} onChange={setFilterStatus} 
                     sort={sortOrder} onSortChange={setSortOrder} />
          <PostList posts={filteredPosts} />
        </>
      ) : (
        <AnalyticsPanel data={analytics!} />
      )}
    </div>
  );
}
```

### R2: Performance Intuition
```tsx
// This component re-renders too often. Why? Fix it.
function LiveFeed({ feedId }: { feedId: string }) {
  const [items, setItems] = useState<FeedItem[]>([]);
  const config = useConfig();
  
  useEffect(() => {
    const ws = new WebSocket(`wss://api.example.com/feed/${feedId}`);
    ws.onmessage = (event) => {
      const newItem = JSON.parse(event.data);
      setItems(prev => [newItem, ...prev].slice(0, 100));
    };
    return () => ws.close();
  }, [feedId]);

  return (
    <div>
      {items.map(item => (
        <FeedCard 
          key={item.id} 
          item={item} 
          theme={config.theme}
          onAction={(action) => handleAction(item.id, action, config)}
        />
      ))}
    </div>
  );
}

function FeedCard({ item, theme, onAction }) {
  return (
    <div style={{ background: theme.cardBg }}>
      <h3>{item.title}</h3>
      <p>{item.content}</p>
      <button onClick={() => onAction('like')}>Like</button>
      <button onClick={() => onAction('share')}>Share</button>
    </div>
  );
}
```

### R3: Design Pattern Judgment
```
My team is debating whether to use the Repository pattern in our Next.js app.
We have: Prisma ORM, ~20 models, Server Components + Server Actions.

Argument FOR: "Clean architecture, separation of concerns, testability"
Argument AGAINST: "Prisma IS the repository, adding another layer is unnecessary abstraction"

Who's right? What would you actually do?
```

## Domain 3: UI Layout (U1-U3)

### U1: Analytics Dashboard
```
Design a SaaS analytics dashboard for a social media management tool.
The user manages 5 social accounts. They need to see:
- Overview metrics (followers, engagement, reach) across all accounts
- Per-account performance comparison
- Content calendar with scheduled posts
- A feed of recent mentions/comments requiring response

Screen: 1440×900 desktop. The user checks this 10+ times/day.
Give me the layout structure, component hierarchy, and spacing strategy.
```

### U2: Mobile-First Form
```
Design a multi-step onboarding form for a fintech app (mobile-first).
Steps:
1. Personal info (name, email, phone)
2. Identity verification (upload ID photo, selfie)
3. Financial profile (income range, employment, investment experience)
4. Risk assessment (5 questions)
5. Account type selection + review

Users are often anxious during this process (giving financial info).
How do you design the flow to reduce anxiety and maximize completion?
```

### U3: Dense Information Display
```
Design a code review interface (like GitHub PR review) that shows:
- File diff (side-by-side or unified)
- Inline comments thread
- Review status per file
- Overall PR metadata (title, description, reviewers, CI status)
- Navigation between changed files

The challenge: there's a LOT of information. How do you create hierarchy
so the reviewer isn't overwhelmed but can drill into any detail?
```

## Domain 4: Visual Design (V1-V3)

### V1: Color System
```
Create a color system for a health/wellness app targeting adults 30-50.
The brand should feel: trustworthy, calm, but not clinical.
I need: primary, secondary, accent, semantic colors (success/warning/error),
neutral scale, and dark mode variants.
Show me the palette with hex values and explain your reasoning.
```

### V2: Typography Scale
```
I'm building a long-form reading app (like Medium or Substack).
Design the typography system:
- Font pairing recommendation
- Size scale (headings, body, captions, UI elements)
- Line height and spacing rules
- How the scale adapts from mobile (375px) to desktop (1440px)

The reading experience should feel effortless — users read 10+ minute articles.
```

### V3: Aesthetic Diagnosis
```
My landing page gets compliments on the copy but people say it 
"looks like a template." It uses:
- Inter font for everything
- Blue (#3B82F6) primary, gray (#6B7280) secondary
- 8px spacing grid
- Tailwind default shadows and rounded corners
- Stock photos from Unsplash

What specifically makes it feel generic? How do I give it a distinctive 
visual identity without a full rebrand?
```

## Domain 5: Design-Code Bridge (B1-B3)

### B1: Component API Design
```
Design the API (props interface) for a reusable <DataTable> component that:
- Supports sorting, filtering, pagination
- Has selectable rows
- Supports custom cell renderers
- Works with server-side and client-side data
- Supports column resizing and reordering

Show me the TypeScript interface and explain your design decisions.
What's the minimum viable API vs the full-featured API?
```

### B2: Design Token Architecture
```
I'm building a design token system for a multi-brand platform 
(think Shopify themes — same components, different visual identities).

How should I structure the token hierarchy? 
What's the relationship between:
- Global tokens (raw values)
- Alias tokens (semantic meaning)  
- Component tokens (component-specific)

Show me the architecture and a concrete example.
```

### B3: Responsive Strategy
```
I have a complex dashboard that works great at 1440px desktop.
Now I need it to work on tablets (768px) and phones (375px).

The dashboard has:
- A left sidebar navigation (collapsible)
- A top metrics bar (4 KPI cards)
- A main content area with a 2-column layout (chart + data table)
- A right panel for details/actions

What's the responsive strategy? At what breakpoints do things change?
Show me the layout at each breakpoint.
```
