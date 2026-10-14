import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { api, ApiError, type Auth, type Booking, type Workshop } from "./api";
import { BookingAttempts } from "./booking-attempts";

const attempts = new BookingAttempts(() => window.sessionStorage);
type View = "workshops" | "bookings" | "admin";
type Notice = {
  kind: "success" | "error";
  message: string;
  requestId?: string | null;
};

export default function App() {
  const [auth, setAuth] = useState<Auth | null>(null);
  const [checking, setChecking] = useState(true);
  const [authFailed, setAuthFailed] = useState(false);
  const [boot, setBoot] = useState(0);
  const [view, setView] = useState<View>("workshops");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [workshops, setWorkshops] = useState<Workshop[]>([]);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [moreWorkshops, setMoreWorkshops] = useState(false);
  const [moreBookings, setMoreBookings] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const generation = useRef(0);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [query, setQuery] = useState("");
  const [cancelId, setCancelId] = useState<string | null>(null);
  const emailInput = useRef<HTMLInputElement>(null);

  const changeAuth = useCallback((next: Auth | null) => {
    generation.current++;
    setBookings([]);
    setCancelId(null);
    setAuth(next);
    if (!next?.user.is_admin)
      setView((current) => (current === "admin" ? "workshops" : current));
  }, []);

  const fail = useCallback(
    (error: unknown) => {
      const problem =
        error instanceof ApiError ? error : new ApiError(0, "network_error");
      setNotice({
        kind: "error",
        message: problem.message,
        requestId: problem.requestId,
      });
      if (problem.status === 401) changeAuth(null);
    },
    [changeAuth],
  );

  useEffect(() => {
    const controller = new AbortController();
    setChecking(true);
    setAuthFailed(false);
    api
      .me(controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) changeAuth(next);
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) changeAuth(null);
        else {
          setAuthFailed(true);
          fail(error);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setChecking(false);
      });
    return () => controller.abort();
  }, [boot, changeAuth, fail]);

  const userId = auth?.user.id;
  const reload = useCallback(
    async (signal?: AbortSignal) => {
      const current = ++generation.current;
      setLoading(true);
      try {
        const [nextWorkshops, nextBookings] = await Promise.all([
          api.workshops(0, signal),
          userId ? api.bookings(0, signal) : Promise.resolve([]),
        ]);
        if (current !== generation.current || signal?.aborted) return;
        setWorkshops(nextWorkshops);
        setBookings(nextBookings);
        setMoreWorkshops(nextWorkshops.length === 50);
        setMoreBookings(nextBookings.length === 50);
        setTitles((old) => ({
          ...old,
          ...Object.fromEntries(
            nextWorkshops.map((row) => [row.id, row.title]),
          ),
        }));
      } catch (error) {
        if (current === generation.current && !signal?.aborted) fail(error);
      } finally {
        if (current === generation.current && !signal?.aborted)
          setLoading(false);
      }
    },
    [userId, fail],
  );

  useEffect(() => {
    if (checking || authFailed) return;
    const controller = new AbortController();
    void reload(controller.signal);
    return () => {
      controller.abort();
      generation.current++;
    };
  }, [checking, authFailed, reload]);

  // History can include workshops beyond the current browsing page.
  useEffect(() => {
    let ignore = false;
    const missing = [...new Set(bookings.map((row) => row.workshop_id))].filter(
      (id) => !titles[id],
    );
    void Promise.all(
      missing.map(async (id) => {
        try {
          const row = await api.workshop(id);
          return [id, row.title] as const;
        } catch {
          return [id, `Workshop ${id.slice(0, 8)}`] as const;
        }
      }),
    ).then((rows) => {
      if (!ignore && rows.length)
        setTitles((old) => ({ ...old, ...Object.fromEntries(rows) }));
    });
    return () => {
      ignore = true;
    };
  }, [bookings, titles]);

  async function perform(action: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setNotice(null);
    try {
      await action();
    } catch (error) {
      fail(error);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const credentials = {
      email: String(data.get("email")).trim(),
      password: String(data.get("password")),
    };
    void perform(async () => {
      if (mode === "register") {
        await api.register(credentials);
        setMode("login");
        setNotice({
          kind: "success",
          message: "Account created. Sign in to reserve your first seat.",
        });
      } else {
        changeAuth(await api.login(credentials));
        setNotice({
          kind: "success",
          message: "Welcome back. Your next workshop is waiting.",
        });
      }
      form.reset();
    });
  }

  function reserve(workshop: Workshop) {
    if (!auth) {
      setMode("login");
      emailInput.current?.focus();
      return;
    }
    const principal = auth;
    void perform(async () => {
      const key = attempts.get(principal.user.id, workshop.id);
      let booking: Booking;
      try {
        booking = await api.book(principal, workshop.id, key);
      } catch (error) {
        if (
          error instanceof ApiError &&
          !error.uncertain &&
          ![401, 403].includes(error.status)
        )
          attempts.finish(principal.user.id, workshop.id);
        throw error;
      }
      attempts.finish(principal.user.id, workshop.id);
      setNotice({
        kind: "success",
        message:
          booking.status === "active"
            ? `Your seat in ${workshop.title} is reserved.`
            : "Your previous booking was cancelled. Select Reserve a seat again for a new booking.",
      });
      await reload();
    });
  }

  function cancel(booking: Booking) {
    if (!auth) return;
    const principal = auth;
    void perform(async () => {
      await api.cancel(principal, booking.id);
      // A recovered booking may still have a pending key from its lost response.
      // Confirmed cancellation ends that attempt; a future reservation needs a new key.
      attempts.finish(principal.user.id, booking.workshop_id);
      setCancelId(null);
      setNotice({
        kind: "success",
        message: "Booking cancelled. Your seat is available to someone else.",
      });
      await reload();
    });
  }

  function loadMore(kind: "workshops" | "bookings") {
    void perform(async () => {
      if (kind === "workshops") {
        const rows = await api.workshops(workshops.length);
        setWorkshops((old) => [...old, ...rows]);
        setMoreWorkshops(rows.length === 50);
        setTitles((old) => ({
          ...old,
          ...Object.fromEntries(rows.map((row) => [row.id, row.title])),
        }));
      } else {
        const rows = await api.bookings(bookings.length);
        setBookings((old) => [...old, ...rows]);
        setMoreBookings(rows.length === 50);
      }
    });
  }

  function createWorkshop(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!auth) return;
    const principal = auth;
    const form = event.currentTarget;
    const data = new FormData(form);
    void perform(async () => {
      await api.createWorkshop(
        principal,
        String(data.get("title")).trim(),
        Number(data.get("capacity")),
      );
      form.reset();
      setNotice({
        kind: "success",
        message: "Workshop created. It is now open for reservations.",
      });
      await reload();
    });
  }

  function updateCapacity(
    event: FormEvent<HTMLFormElement>,
    workshop: Workshop,
  ) {
    event.preventDefault();
    if (!auth) return;
    const principal = auth;
    const capacity = Number(new FormData(event.currentTarget).get("capacity"));
    void perform(async () => {
      await api.capacity(principal, workshop.id, capacity);
      setNotice({
        kind: "success",
        message: `Capacity updated for ${workshop.title}.`,
      });
      await reload();
    });
  }

  const disabled = busy || checking || authFailed || loading;
  const active = new Set(
    bookings
      .filter((row) => row.status === "active")
      .map((row) => row.workshop_id),
  );
  const visible = workshops.filter((row) =>
    row.title.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <div className="header-inner">
          <a className="brand" href="/" aria-label="LabPass home">
            <span className="brand-mark" aria-hidden="true">
              L<span>↗</span>
            </span>
            LabPass<span className="brand-dot">.</span>
          </a>
          <nav aria-label="Main navigation">
            <button
              className={view === "workshops" ? "nav-active" : ""}
              onClick={() => setView("workshops")}
            >
              Workshops
            </button>
            <button
              className={view === "bookings" ? "nav-active" : ""}
              onClick={() => setView("bookings")}
            >
              My bookings
            </button>
            {auth?.user.is_admin && (
              <button
                className={view === "admin" ? "nav-active" : ""}
                onClick={() => setView("admin")}
              >
                Manage workshops
              </button>
            )}
          </nav>
          <div className="account-nav">
            {auth ? (
              <>
                <span className="email" title={auth.user.email}>
                  {auth.user.email}
                </span>
                <button
                  className="quiet-button"
                  disabled={disabled}
                  onClick={() =>
                    void perform(async () => {
                      await api.logout(auth);
                      changeAuth(null);
                      setNotice({
                        kind: "success",
                        message: "You have signed out.",
                      });
                    })
                  }
                >
                  Sign out
                </button>
              </>
            ) : (
              <span className="header-note">Learn together. Go further.</span>
            )}
          </div>
        </div>
      </header>
      <main id="main" className="page">
        <section className="hero" aria-labelledby="hero-title">
          <div>
            <p className="eyebrow">
              <span className="tiny-dot" /> CLOUD & DEVOPS WORKSHOPS
            </p>
            <h1 id="hero-title">
              A seat for your
              <br />
              <em>next step.</em>
            </h1>
            <p className="hero-copy">
              Build your skills, find your people, and put ideas into practice.
              <br className="desktop-break" /> Your next workshop starts with a
              free seat.
            </p>
          </div>
          <div className="hero-art" aria-hidden="true">
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <div className="ticket">
              <span>LABPASS / ADMIT ONE</span>
              <div>
                Keep
                <br />
                building.
              </div>
              <span className="ticket-bottom">YOUR NEXT STEP ↗</span>
            </div>
            <div className="art-spark">✳</div>
          </div>
        </section>
        {notice && (
          <div
            className={`notice ${notice.kind}`}
            role={notice.kind === "error" ? "alert" : "status"}
          >
            <span>
              {notice.message}
              {notice.requestId && (
                <small>Request reference: {notice.requestId}</small>
              )}
            </span>
            <button
              aria-label="Dismiss message"
              onClick={() => setNotice(null)}
            >
              ×
            </button>
          </div>
        )}
        {authFailed && (
          <div className="recovery">
            <p>We could not check your session.</p>
            <button
              className="button"
              disabled={checking}
              onClick={() => setBoot((old) => old + 1)}
            >
              Retry connection
            </button>
          </div>
        )}
        <div className="content-grid">
          <section
            className="main-content"
            aria-label={
              view === "workshops"
                ? "Workshop browser"
                : view === "bookings"
                  ? "Booking history"
                  : "Workshop administration"
            }
          >
            <div className="section-heading">
              <div>
                <p className="eyebrow">
                  {view === "workshops"
                    ? "FIND YOUR NEXT CHALLENGE"
                    : view === "bookings"
                      ? "YOUR LEARNING JOURNEY"
                      : "ADMIN WORKSPACE"}
                </p>
                <h2>
                  {view === "workshops"
                    ? "Explore workshops"
                    : view === "bookings"
                      ? "My bookings"
                      : "Manage workshops"}
                </h2>
              </div>
              <button
                className="refresh-button"
                disabled={disabled}
                onClick={() => {
                  setNotice(null);
                  void reload();
                }}
              >
                ↻ <span>Refresh</span>
              </button>
            </div>
            {loading && !authFailed && (
              <p className="loading" role="status">
                Loading workshops and bookings…
              </p>
            )}
            {view === "workshops" && (
              <>
                <label className="search">
                  <span aria-hidden="true">⌕</span>
                  <input
                    type="search"
                    aria-label="Search loaded workshops"
                    placeholder="Search loaded workshops"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                  <span className="count">{visible.length} shown</span>
                </label>
                <div className="workshop-list">
                  {visible.map((workshop, index) => (
                    <article
                      className="workshop-card"
                      key={workshop.id}
                      aria-label={workshop.title}
                    >
                      <div
                        className={`workshop-icon shade-${index % 3}`}
                        aria-hidden="true"
                      >
                        {index % 3 === 0 ? ">_" : index % 3 === 1 ? "{ }" : "⌘"}
                      </div>
                      <div className="workshop-info">
                        <div className="card-meta">
                          <span>HANDS-ON WORKSHOP</span>
                          <span className="free-tag">Free</span>
                        </div>
                        <h3>{workshop.title}</h3>
                        <p>Cloud & DevOps · Learn by doing</p>
                        <div className="availability">
                          <span
                            className={
                              workshop.available === 0
                                ? "seat-dot full"
                                : "seat-dot"
                            }
                          />
                          <span>
                            <strong>{workshop.available}</strong> of{" "}
                            {workshop.capacity} seats available
                          </span>
                        </div>
                        <progress
                          max={Math.max(1, workshop.capacity)}
                          value={workshop.reserved}
                          aria-label={`${workshop.title}: ${workshop.reserved} seats reserved`}
                        />
                      </div>
                      <button
                        className={
                          active.has(workshop.id) ? "button booked" : "button"
                        }
                        disabled={
                          disabled ||
                          active.has(workshop.id) ||
                          (workshop.available === 0 &&
                            !(
                              auth &&
                              attempts.pending(auth.user.id, workshop.id)
                            ))
                        }
                        onClick={() => reserve(workshop)}
                      >
                        {active.has(workshop.id)
                          ? "Seat reserved ✓"
                          : auth && attempts.pending(auth.user.id, workshop.id)
                            ? "Retry reservation ↗"
                            : workshop.available === 0
                              ? "Fully booked"
                              : auth
                                ? "Reserve a seat ↗"
                                : "Sign in to reserve ↗"}
                      </button>
                    </article>
                  ))}
                </div>
                {!loading && visible.length === 0 && (
                  <div className="empty">
                    <h3>
                      {query
                        ? "No matches on this page"
                        : "Workshops are on their way"}
                    </h3>
                    <p>
                      {query
                        ? "Try a different search or load more workshops."
                        : "Refresh later to see new workshops."}
                    </p>
                  </div>
                )}
                {moreWorkshops && (
                  <button
                    className="load-more"
                    disabled={disabled}
                    onClick={() => loadMore("workshops")}
                  >
                    Load more workshops
                  </button>
                )}
                <p className="snapshot-note">
                  Availability is a snapshot. Your seat is confirmed when your
                  booking succeeds.
                </p>
              </>
            )}
            {view === "bookings" && (
              <>
                {!auth ? (
                  <div className="empty">
                    <h3>Your next chapter starts here</h3>
                    <p>Sign in to see your reservations and booking history.</p>
                  </div>
                ) : (
                  <>
                    <div className="booking-list">
                      {bookings.map((booking) => (
                        <article
                          className="booking-card"
                          key={booking.id}
                          aria-label={`Booking for ${titles[booking.workshop_id] || "workshop"}`}
                        >
                          <div>
                            <span className={`status-pill ${booking.status}`}>
                              {booking.status === "active"
                                ? "Reserved"
                                : "Cancelled"}
                            </span>
                            <h3>
                              {titles[booking.workshop_id] ||
                                "Loading workshop…"}
                            </h3>
                            <p>
                              Booked{" "}
                              {new Date(booking.created_at).toLocaleDateString(
                                undefined,
                                {
                                  day: "numeric",
                                  month: "short",
                                  year: "numeric",
                                },
                              )}
                            </p>
                            <small className="booking-reference">
                              Booking reference: {booking.id}
                            </small>
                          </div>
                          {booking.status === "active" &&
                            (cancelId === booking.id ? (
                              <div className="cancel-confirm">
                                <p>Release your seat?</p>
                                <button
                                  className="button danger"
                                  disabled={disabled}
                                  onClick={() => cancel(booking)}
                                >
                                  Confirm cancellation
                                </button>
                                <button
                                  className="text-button"
                                  disabled={busy}
                                  onClick={() => setCancelId(null)}
                                >
                                  Keep my seat
                                </button>
                              </div>
                            ) : (
                              <button
                                className="text-button"
                                disabled={disabled}
                                onClick={() => setCancelId(booking.id)}
                              >
                                Cancel booking
                              </button>
                            ))}
                        </article>
                      ))}
                    </div>
                    {!loading && bookings.length === 0 && (
                      <div className="empty">
                        <h3>Room for something new</h3>
                        <p>
                          You have no bookings yet. Find a workshop that sparks
                          your curiosity.
                        </p>
                        <button
                          className="button"
                          onClick={() => setView("workshops")}
                        >
                          Explore workshops ↗
                        </button>
                      </div>
                    )}
                    {moreBookings && (
                      <button
                        className="load-more"
                        disabled={disabled}
                        onClick={() => loadMore("bookings")}
                      >
                        Load older bookings
                      </button>
                    )}
                  </>
                )}
              </>
            )}
            {view === "admin" && auth?.user.is_admin && (
              <>
                <form className="admin-create" onSubmit={createWorkshop}>
                  <h3>Create a workshop</h3>
                  <label>
                    Workshop title
                    <input name="title" required maxLength={200} />
                  </label>
                  <label>
                    Capacity
                    <input
                      name="capacity"
                      type="number"
                      required
                      min={0}
                      max={1000000}
                      step={1}
                      defaultValue={20}
                    />
                  </label>
                  <button className="button" disabled={disabled}>
                    Create workshop
                  </button>
                  <p className="form-note">
                    Capacity may be zero. New workshops appear in the public
                    list.
                  </p>
                </form>
                {workshops.map((workshop) => (
                  <form
                    className="capacity-form"
                    key={`${workshop.id}:${workshop.capacity}`}
                    onSubmit={(event) => updateCapacity(event, workshop)}
                    aria-label={`Capacity for ${workshop.title}`}
                  >
                    <div>
                      <h3>{workshop.title}</h3>
                      <p>
                        {workshop.reserved} reserved · {workshop.available}{" "}
                        available
                      </p>
                    </div>
                    <label>
                      Capacity
                      <input
                        name="capacity"
                        aria-label={`Capacity for ${workshop.title}`}
                        type="number"
                        required
                        min={0}
                        max={1000000}
                        step={1}
                        defaultValue={workshop.capacity}
                      />
                    </label>
                    <button className="button secondary" disabled={disabled}>
                      Save capacity
                    </button>
                  </form>
                ))}
                {moreWorkshops && (
                  <button
                    className="load-more"
                    disabled={disabled}
                    onClick={() => loadMore("workshops")}
                  >
                    Load more workshops
                  </button>
                )}
              </>
            )}
          </section>
          <aside className="sidebar" aria-label="Your account">
            {!auth ? (
              <section className="auth-panel">
                <span className="panel-symbol" aria-hidden="true">
                  ↗
                </span>
                <h2>
                  {mode === "login"
                    ? "Good to see you."
                    : "Make yourself at home."}
                </h2>
                <p>
                  {mode === "login"
                    ? "Sign in, pick a workshop, and save your spot."
                    : "One account. Your next learning adventure."}
                </p>
                <div className="auth-tabs" aria-label="Account action">
                  <button
                    aria-pressed={mode === "login"}
                    disabled={busy}
                    onClick={() => setMode("login")}
                  >
                    Sign in
                  </button>
                  <button
                    aria-pressed={mode === "register"}
                    disabled={busy}
                    onClick={() => setMode("register")}
                  >
                    Create account
                  </button>
                </div>
                <form onSubmit={submitAuth}>
                  <label>
                    Email address
                    <input
                      ref={emailInput}
                      name="email"
                      type="email"
                      autoComplete="username"
                      required
                      maxLength={254}
                      placeholder="you@example.com"
                      disabled={busy || checking || authFailed}
                    />
                  </label>
                  <label>
                    Password
                    <input
                      key={mode}
                      name="password"
                      type="password"
                      autoComplete={
                        mode === "register"
                          ? "new-password"
                          : "current-password"
                      }
                      required
                      minLength={mode === "register" ? 12 : 1}
                      maxLength={128}
                      disabled={busy || checking || authFailed}
                    />
                  </label>
                  {mode === "register" && (
                    <p className="form-note">
                      Use 12–128 characters. Your account starts as a regular
                      member.
                    </p>
                  )}
                  <button
                    className="button auth-submit"
                    disabled={busy || checking || authFailed}
                  >
                    {checking
                      ? "Checking session…"
                      : busy
                        ? "Please wait…"
                        : mode === "login"
                          ? "Sign in →"
                          : "Create account →"}
                  </button>
                </form>
              </section>
            ) : (
              <section className="member-panel">
                <span className="member-avatar" aria-hidden="true">
                  {auth.user.email.slice(0, 1).toUpperCase()}
                </span>
                <p className="eyebrow">
                  {auth.user.is_admin
                    ? "ADMINISTRATOR"
                    : "YOU’RE IN GOOD COMPANY"}
                </p>
                <h2>
                  Keep your
                  <br />
                  momentum.
                </h2>
                <p className="member-email">{auth.user.email}</p>
                <button
                  className="button secondary"
                  onClick={() => setView("bookings")}
                >
                  View my bookings ↗
                </button>
                <p className="form-note">
                  Your reservations and past workshops, all in one place.
                </p>
              </section>
            )}
            <section className="how-it-works">
              <p className="eyebrow">A LITTLE ROOM TO GROW</p>
              <h3>
                Show up curious.
                <br />
                Leave with more.
              </h3>
              <ol>
                <li>
                  <span>01</span>
                  <div>
                    <strong>Find your workshop</strong>
                    <p>Choose your next cloud or DevOps challenge.</p>
                  </div>
                </li>
                <li>
                  <span>02</span>
                  <div>
                    <strong>Reserve a free seat</strong>
                    <p>A small commitment to your next big idea.</p>
                  </div>
                </li>
                <li>
                  <span>03</span>
                  <div>
                    <strong>Keep learning</strong>
                    <p>Manage your plans from My bookings.</p>
                  </div>
                </li>
              </ol>
            </section>
          </aside>
        </div>
        <footer>
          <span className="footer-brand">LabPass.</span>
          <span>Built for curious minds. Made for the next step.</span>
          <span>Cloud & DevOps / Free workshops</span>
        </footer>
      </main>
    </>
  );
}
