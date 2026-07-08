# HoopStar.ai — Android Integration Guide for Claude Code

> **READ THIS FIRST.**
> You are Claude Code running inside Android Studio. Your job is to build a complete Android application
> that connects to an existing FastAPI backend. Every action the user previously ran as a terminal
> `curl` command must become a tap in this app. Follow every section in order. Do not skip steps.
> Do not ask the user to do anything manually that you can automate.

---

## 1. Project Context & Objective

### What the backend already does
The HoopStar.ai backend is a fully operational FastAPI service running in Docker. It processes
basketball video files through a GPU CV pipeline (Modal Labs), detects players, reads jersey
numbers via OCR, maps players to a coached roster, and generates annotated highlight reels.

**The backend base URL is:**
```
https://thrift-fraying-plentiful.ngrok-free.dev
```
Store this as a default in `AppPreferences` and allow the user to override it from the Settings screen.

### What you are building
A production-grade Android app (Kotlin + Jetpack Compose + MVVM) that replaces every manual
`curl` command with a polished UI interaction. The complete user journey is:

```
Upload video → wait for processing → run player mapping →
pick a player → extract annotated highlight reel →
compose reel with music/intro → stream & watch → share
```

### Known team and roster data (hard-code as defaults, make overridable later)
```
Team ID : 13  (Bremen)

Player roster:
  player_id=39  jersey=22  Raylon Moats
  player_id=40  jersey=10  Colton Large
  player_id=36  jersey=23  Preston Brookins
  player_id=34  jersey=24  Blayze Hensley
  player_id=37  jersey=52  Brayden Gunnels
  player_id=38  jersey=40  Owen Nunemaker
  player_id=35  jersey=43  Cayden Bradley
  player_id=41  jersey=1   David Monesmith
  player_id=42  jersey=15  Ian Pepin
```

### Tech stack to use — no alternatives
- **Language**: Kotlin
- **UI**: Jetpack Compose (no XML layouts)
- **Architecture**: MVVM (ViewModel + Repository)
- **Async**: Kotlin Coroutines + StateFlow
- **Networking**: Retrofit 2 + OkHttp 4 + Moshi
- **Video playback**: ExoPlayer (media3)
- **Images**: Coil
- **DI**: Hilt
- **Storage**: EncryptedSharedPreferences
- **Min SDK**: 26

---

## 2. UI/UX Audit & Generation

### Instruction to Claude Code
Scan the existing project for any Composable screens. If the project is brand-new or missing any
of the screens listed below, **create them from scratch**. Every screen must be implemented
before you wire up any networking or state logic.

### Required screens — build all of these

#### Screen 1 — Setup / Login (`SetupScreen.kt`)
- Full-screen centered card
- Text field: "Backend URL" — pre-filled with the ngrok URL above
- Primary button: "Connect & Validate"
- On tap: call `GET /health/` and show a green checkmark on success or a red error banner on failure
- On success: navigate to Jobs Dashboard and persist the URL

#### Screen 2 — Jobs Dashboard (`JobsDashboardScreen.kt`)
- Top app bar: "HoopStar.ai" title + refresh icon button
- Floating Action Button (FAB) with a camera/upload icon → navigates to Upload screen
- LazyColumn of job cards. Each card shows:
  - Job ID (bold)
  - Status pill (color-coded: green=completed, amber=processing, red=failed, grey=pending/canceled)
  - Source filename (truncated to one line)
  - Progress bar (visible only when status is "processing", value = `progress_percent / 100`)
  - "Created" timestamp formatted as relative time (e.g. "2h ago")
- Tap a card → navigate to Job Detail
- Pull-to-refresh gesture to reload all jobs
- Empty state: centered illustration + "No jobs yet. Tap + to upload a video."

> **Note**: There is no `GET /api/videos` list endpoint. Persist a local list of `job_id`s in
> `EncryptedSharedPreferences` (comma-separated string). Fetch each job's status individually.
> Fetch them in parallel using `async { }` inside a `coroutineScope { }`.

#### Screen 3 — Upload Screen (`UploadScreen.kt`)
- Team ID field (pre-filled: 13)
- File picker button: "Choose Video" — opens the system file picker, filtered to `video/*`
- Show selected filename and file size once picked
- Primary button: "Upload & Process"
- Uploading state: linear progress bar + "Uploading…" label
- On success: show the returned `job_id`, save it to local preferences, navigate back to dashboard

#### Screen 4 — Job Detail Screen (`JobDetailScreen.kt`)
- Header card: job ID, status pill, filename, processed/total frames, progress percent, duration
- Section: "Player Mapping"
  - Button: "Run Player Mapping" — calls `POST /api/videos/{job_id}/player_mapping/auto?team_id=13`
  - After success: show a lazy list of mapping results. Each row shows jersey number, player name,
    match rating pill (green=high/low, red=no_match), and frame count
- Section: "Generate Highlight Reel"
  - Dropdown/chip selector: pick a player from the roster (show jersey + name)
  - Button: "Generate Annotated Reel" — calls extract then compose sequentially
  - Two-step progress display:
    - Step 1 of 2: "Extracting clips…" with spinner (this call can take 5–10 min — never timeout)
    - Step 2 of 2: "Composing reel…" with spinner
  - On success: navigate to Reel Player screen
- Section: "Reels" — list of previously generated reels for this job (from local cache)

#### Screen 5 — Reel Player Screen (`ReelPlayerScreen.kt`)
- Full-screen ExoPlayer surface
- Stream video directly from the backend download URL (do NOT download to disk first)
- Overlay: player name + jersey number + reel duration in top-left corner
- Custom playback controls: play/pause, seek bar, time label
- Share button (top-right): use Android share sheet to share the download URL
- Download button: save MP4 to device Downloads folder via `DownloadManager`

#### Screen 6 — Settings Screen (`SettingsScreen.kt`)
- Backend URL field (editable, with a "Save & Reconnect" button)
- "Clear Job History" button (clears persisted job IDs from EncryptedSharedPreferences)
- App version label

### Visual style — enforce this across all screens
- Dark theme (background `#0D0D0D`, surface `#1A1A1A`)
- Accent color: `#FF6B35` (HoopStar orange)
- Typography: `MaterialTheme.typography` — use `headlineMedium` for titles, `bodyMedium` for body
- Card elevation: 2dp, corner radius: 12dp
- Status pill shape: stadium (fully rounded), padding 4dp vertical / 10dp horizontal
- No loading state should block the entire screen — use inline spinners inside buttons

---

## 3. API & Network Layer

### Instruction to Claude Code
Create the following files exactly as specified. Do not improvise method names or package
structure. The Retrofit interface must match the backend contract precisely.

### File: `network/HoopStarApi.kt`

```kotlin
interface HoopStarApi {

    // Health
    @GET("health/")
    suspend fun health(): HealthDto

    // Job status (there is no list endpoint — fetch by ID)
    @GET("api/videos/{jobId}")
    suspend fun getJobStatus(@Path("jobId") jobId: Int): VideoJobStatusDto

    // Upload (multipart form)
    @Multipart
    @POST("api/videos/upload")
    suspend fun uploadVideo(
        @Part file: MultipartBody.Part,
        @Part("team_id") teamId: RequestBody
    ): VideoUploadResponseDto

    // Cancel job
    @POST("api/videos/{jobId}/cancel")
    suspend fun cancelJob(@Path("jobId") jobId: Int): CancelResponseDto

    // Player mapping
    @POST("api/videos/{jobId}/player_mapping/auto")
    suspend fun runPlayerMapping(
        @Path("jobId") jobId: Int,
        @Query("team_id") teamId: Int = 13
    ): PlayerMappingResponseDto

    // Highlight extract (source defaults to "annotated" on the backend)
    @POST("api/videos/{jobId}/highlights/extract")
    suspend fun extractHighlights(
        @Path("jobId") jobId: Int,
        @Query("player_id") playerId: Int,
        @Query("source") source: String = "annotated"
    ): HighlightReelDto

    // Highlight compose
    @POST("api/videos/{jobId}/highlights/{reelId}/compose")
    suspend fun composeReel(
        @Path("jobId") jobId: Int,
        @Path("reelId") reelId: Int
    ): ComposedReelDto

    // Annotated export (full-game)
    @POST("api/videos/{jobId}/exports/annotated")
    suspend fun createAnnotatedExport(@Path("jobId") jobId: Int): AnnotatedExportDto

    @GET("api/videos/{jobId}/exports/annotated/{exportId}")
    suspend fun getAnnotatedExport(
        @Path("jobId") jobId: Int,
        @Path("exportId") exportId: String
    ): AnnotatedExportStatusDto
}
```

### File: `network/dto/Dtos.kt`
Define all DTOs with `@JsonClass(generateAdapter = true)`. Here are the exact field names
matching the backend JSON:

```kotlin
@JsonClass(generateAdapter = true)
data class HealthDto(val status: String, val database: String)

@JsonClass(generateAdapter = true)
data class VideoUploadResponseDto(val job_id: Int, val status: String, val message: String)

@JsonClass(generateAdapter = true)
data class VideoJobStatusDto(
    val job_id: Int,
    val team_id: Int,
    val status: String,          // "pending"|"processing"|"completed"|"failed"|"canceled"
    val source_filename: String,
    val total_frames: Int?,
    val processed_frames: Int,
    val progress_percent: Float?,
    val processing_duration_sec: Float?,
    val error_message: String?,
    val created_at: String,
    val updated_at: String
)

@JsonClass(generateAdapter = true)
data class CancelResponseDto(val job_id: Int, val status: String, val message: String)

@JsonClass(generateAdapter = true)
data class PlayerMappingSuggestionDto(
    val track_id: Int,
    val detected_jersey: Int,
    val frame_count: Int,
    val confidence_mean: Float,
    val confidence_max: Float,
    val suggested_player_id: Int?,
    val suggested_player_name: String?,
    val match_rating: String       // "high"|"medium"|"low"|"no_match"
)

@JsonClass(generateAdapter = true)
data class PlayerMappingResponseDto(
    val job_id: Int,
    val team_id: Int,
    val total_mappings: Int,
    val high_confidence_count: Int,
    val medium_confidence_count: Int,
    val low_confidence_count: Int,
    val no_match_count: Int,
    val mappings: List<PlayerMappingSuggestionDto>
)

@JsonClass(generateAdapter = true)
data class HighlightClipDto(
    val clip_id: Int,
    val order_index: Int,
    val event_type: String,
    val track_id: Int?,
    val mapped_player_id: Int?,
    val start_timestamp_sec: Float,
    val end_timestamp_sec: Float,
    val score: Float,
    val confidence: Float,
    val download_url: String?
)

@JsonClass(generateAdapter = true)
data class HighlightReelDto(
    val reel_id: Int,
    val job_id: Int,
    val team_id: Int,
    val status: String,
    val scope: String,
    val source_mode: String,
    val player_id: Int?,
    val clip_count: Int,
    val total_duration_sec: Float,
    val output_filename: String?,
    val download_url: String?,
    val created_at: String,
    val clips: List<HighlightClipDto>
)

@JsonClass(generateAdapter = true)
data class ComposedReelDto(
    val composed_reel_id: Int,
    val reel_id: Int,
    val job_id: Int,
    val team_id: Int,
    val player_id: Int?,
    val status: String,
    val aspect_ratio: String,
    val music_track: String?,
    val has_intro: Boolean,
    val has_stats: Boolean,
    val has_watermark: Boolean,
    val total_duration_sec: Float,
    val output_filename: String?,
    val download_url: String,
    val created_at: String
)

@JsonClass(generateAdapter = true)
data class AnnotatedExportDto(
    val job_id: Int,
    val export_id: String,
    val status: String,
    val output_filename: String,
    val download_url: String,
    val created_at: String,
    val total_frames: Int?,
    val rendered_frames: Int
)

@JsonClass(generateAdapter = true)
data class AnnotatedExportStatusDto(
    val job_id: Int,
    val export_id: String,
    val status: String,
    val output_filename: String,
    val download_url: String,
    val created_at: String,
    val total_frames: Int?,
    val rendered_frames: Int,
    val file_size_bytes: Long?
)
```

### File: `di/NetworkModule.kt`

```kotlin
@Module @InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides @Singleton
    fun provideOkHttp(): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(600, TimeUnit.SECONDS)   // extract/compose take up to 10 min — never lower this
        .writeTimeout(120, TimeUnit.SECONDS)
        .addInterceptor(HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        })
        .build()

    @Provides @Singleton
    fun provideMoshi(): Moshi = Moshi.Builder().addLast(KotlinJsonAdapterFactory()).build()

    @Provides @Singleton
    fun provideRetrofit(okHttp: OkHttpClient, moshi: Moshi, prefs: AppPreferences): Retrofit =
        Retrofit.Builder()
            .baseUrl(prefs.baseUrl)          // loaded from EncryptedSharedPreferences
            .client(okHttp)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()

    @Provides @Singleton
    fun provideApi(retrofit: Retrofit): HoopStarApi = retrofit.create(HoopStarApi::class.java)
}
```

### Error handling — apply to every repository call
Wrap every Retrofit call in:
```kotlin
try {
    Result.success(api.someCall())
} catch (e: HttpException) {
    Result.failure(Exception("Server error ${e.code()}: ${e.message()}"))
} catch (e: IOException) {
    Result.failure(Exception("Network error: check connection"))
}
```
Expose `Result<T>` from repositories. Never let exceptions reach the ViewModel unhandled.

---

## 4. State Management & ViewModel

### Instruction to Claude Code
Create one ViewModel per screen. Use `StateFlow<UiState>` for all UI state. Never use
`LiveData`. Never expose mutable state directly. All network calls must run inside
`viewModelScope.launch { }` — never on the main thread.

### File: `viewmodel/JobDetailViewModel.kt`

This is the most important ViewModel. It drives the entire reel generation flow:

```kotlin
@HiltViewModel
class JobDetailViewModel @Inject constructor(
    private val repo: HoopStarRepository,
    private val prefs: AppPreferences,
    savedState: SavedStateHandle
) : ViewModel() {

    private val jobId: Int = savedState["jobId"]!!

    // Single unified UI state
    sealed class UiState {
        object Idle : UiState()
        data class Loading(val step: String, val stepIndex: Int, val totalSteps: Int) : UiState()
        data class MappingResult(val response: PlayerMappingResponseDto) : UiState()
        data class ReelReady(val composed: ComposedReelDto, val streamUrl: String) : UiState()
        data class Error(val message: String) : UiState()
    }

    private val _jobStatus = MutableStateFlow<VideoJobStatusDto?>(null)
    val jobStatus: StateFlow<VideoJobStatusDto?> = _jobStatus.asStateFlow()

    private val _uiState = MutableStateFlow<UiState>(UiState.Idle)
    val uiState: StateFlow<UiState> = _uiState.asStateFlow()

    init { loadJob() }

    fun loadJob() = viewModelScope.launch {
        repo.getJobStatus(jobId).onSuccess { _jobStatus.value = it }
    }

    fun runMapping() = viewModelScope.launch {
        _uiState.value = UiState.Loading("Running player mapping…", 1, 1)
        repo.runPlayerMapping(jobId, teamId = 13)
            .onSuccess { _uiState.value = UiState.MappingResult(it) }
            .onFailure { _uiState.value = UiState.Error(it.message ?: "Mapping failed") }
    }

    fun generateReel(playerId: Int) = viewModelScope.launch {
        // Step 1 — Extract (slow: up to 10 min on CPU backend)
        _uiState.value = UiState.Loading("Extracting annotated clips…", 1, 2)
        val reelResult = repo.extractHighlights(jobId, playerId)
        if (reelResult.isFailure) {
            _uiState.value = UiState.Error(reelResult.exceptionOrNull()?.message ?: "Extract failed")
            return@launch
        }
        val reel = reelResult.getOrThrow()

        // Step 2 — Compose
        _uiState.value = UiState.Loading("Composing reel with music…", 2, 2)
        val composeResult = repo.composeReel(jobId, reel.reel_id)
        if (composeResult.isFailure) {
            _uiState.value = UiState.Error(composeResult.exceptionOrNull()?.message ?: "Compose failed")
            return@launch
        }
        val composed = composeResult.getOrThrow()
        val streamUrl = "${prefs.baseUrl.trimEnd('/')}${composed.download_url}"
        _uiState.value = UiState.ReelReady(composed, streamUrl)
    }
}
```

### File: `viewmodel/JobsDashboardViewModel.kt`

```kotlin
@HiltViewModel
class JobsDashboardViewModel @Inject constructor(
    private val repo: HoopStarRepository,
    private val prefs: AppPreferences
) : ViewModel() {

    private val _jobs = MutableStateFlow<List<VideoJobStatusDto>>(emptyList())
    val jobs: StateFlow<List<VideoJobStatusDto>> = _jobs.asStateFlow()

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    init { refresh() }

    fun refresh() = viewModelScope.launch {
        _isLoading.value = true
        val ids = prefs.savedJobIds  // List<Int> from EncryptedSharedPreferences
        val results = ids.map { id -> async { repo.getJobStatus(id) } }
            .awaitAll()
            .mapNotNull { it.getOrNull() }
            .sortedByDescending { it.created_at }
        _jobs.value = results
        _isLoading.value = false
    }

    fun addJobId(id: Int) {
        prefs.savedJobIds = (prefs.savedJobIds + id).distinct()
        refresh()
    }
}
```

### File: `data/HoopStarRepository.kt`
Create a single repository that delegates to `HoopStarApi` and wraps every call in the
`Result<T>` pattern described in Section 3. All functions must be `suspend` functions.

---

## 5. Step-by-Step Execution Plan

Follow these steps **in strict order**. Do not move to the next step until the current one compiles
and runs without errors.

### Step 1 — Project Bootstrap
- [ ] Verify `build.gradle.kts` (app) contains all required dependencies (Retrofit, Moshi,
      ExoPlayer media3, Coil, Hilt, Coroutines). Add any that are missing.
- [ ] Verify `AndroidManifest.xml` has `INTERNET` permission and
      `android:usesCleartextTraffic="true"` (required for local ngrok fallback).
- [ ] Add `@HiltAndroidApp` annotation to the Application class. Create it if missing.
- [ ] Set up the Hilt component hierarchy: Application → Activity → ViewModel.

### Step 2 — Preferences Layer
- [ ] Create `AppPreferences.kt` using `EncryptedSharedPreferences`.
- [ ] Expose: `baseUrl: String` (default: `https://thrift-fraying-plentiful.ngrok-free.dev`),
      `savedJobIds: List<Int>` (stored as comma-separated string), `authToken: String` (empty
      for now, reserved).

### Step 3 — Network Layer
- [ ] Create all DTO files as defined in Section 3.
- [ ] Create `HoopStarApi.kt` interface exactly as defined.
- [ ] Create `NetworkModule.kt` Hilt module exactly as defined.
- [ ] Create `HoopStarRepository.kt` wrapping every API call in `Result<T>`.
- [ ] **Verify**: Write a simple unit test that mocks `HoopStarApi.health()` and asserts
      `HealthDto(status="ok", database="connected")` is returned.

### Step 4 — Navigation Graph
- [ ] Create `NavGraph.kt` using Compose Navigation.
- [ ] Define routes: `setup`, `dashboard`, `upload`, `job_detail/{jobId}`,
      `reel_player/{jobId}/{reelId}/{composedId}`, `settings`.
- [ ] Wire the start destination: if `prefs.baseUrl` is empty → `setup`, otherwise → `dashboard`.

### Step 5 — Setup Screen
- [ ] Implement `SetupScreen.kt` and `SetupViewModel.kt`.
- [ ] The "Connect & Validate" button calls `GET /health/`, shows success/failure inline.
- [ ] On success: persist URL, navigate to dashboard.

### Step 6 — Jobs Dashboard Screen
- [ ] Implement `JobsDashboardScreen.kt` and `JobsDashboardViewModel.kt`.
- [ ] Job cards must show: ID, status pill (color-coded), filename, progress bar (processing only),
      relative time.
- [ ] Pull-to-refresh must re-fetch all job statuses in parallel.
- [ ] FAB navigates to Upload screen.

### Step 7 — Upload Screen
- [ ] Implement `UploadScreen.kt` and `UploadViewModel.kt`.
- [ ] File picker must filter to `video/*`.
- [ ] On upload success: call `viewModel.addJobId(jobId)` on the dashboard ViewModel, navigate back.
- [ ] Show real upload progress using `RequestBody` with a progress callback.

### Step 8 — Job Detail Screen
- [ ] Implement `JobDetailScreen.kt` and `JobDetailViewModel.kt` exactly as specified in Section 4.
- [ ] The loading state must show which step is running (e.g. "Step 1 of 2: Extracting clips…").
- [ ] The player picker must list all 9 roster players with jersey number + name.
- [ ] **Do not set a timeout** on the extract/compose calls — they are synchronous and can take
      10 minutes. The coroutine must stay alive.

### Step 9 — Reel Player Screen
- [ ] Implement `ReelPlayerScreen.kt`.
- [ ] Use `ExoPlayer` with a `PlayerView` / `AndroidView` inside Compose.
- [ ] Load video from the stream URL directly (no download to disk).
- [ ] Show player name + jersey in an overlay at top-left.
- [ ] Share button: fire an `Intent.ACTION_SEND` with the stream URL as text.
- [ ] Download button: use `DownloadManager` to save MP4 to `Environment.DIRECTORY_DOWNLOADS`.

### Step 10 — Settings Screen
- [ ] Implement `SettingsScreen.kt`.
- [ ] "Save & Reconnect" must update `prefs.baseUrl` AND recreate the Retrofit instance.
      Do this by exposing the base URL as a `MutableStateFlow` that `NetworkModule` observes,
      or by re-injecting a new Retrofit via a `Provider<Retrofit>`.

### Step 11 — Polish & Error States
- [ ] Every screen must have an empty state composable when there is no data.
- [ ] Every error must surface as a `Snackbar` or inline error card — never a silent failure.
- [ ] All buttons must show a `CircularProgressIndicator` while their action is in-flight and
      become disabled to prevent double-taps.
- [ ] Status pills: green for `completed`, amber for `processing`, red for `failed`/`no_match`,
      grey for `pending`/`canceled`.

### Step 12 — Final Verification Checklist
- [ ] `GET /health/` → Setup screen shows "Connected ✓"
- [ ] `GET /api/videos/22` → Job card shows status=completed, filename=bremenvstriton15.mp4
- [ ] `POST /api/videos/22/player_mapping/auto?team_id=13` → 30 matched tracks shown in list
- [ ] Generate reel for Raylon Moats (player_id=39) → ExoPlayer streams the composed reel
- [ ] Share button fires the share sheet with the download URL
- [ ] Download button saves MP4 to Downloads folder
- [ ] Settings screen can update the base URL and reconnect successfully

---

## 6. Backend Endpoint Quick Reference

| Action | Method | Path | Key params |
|---|---|---|---|
| Health check | `GET` | `/health/` | — |
| Get job | `GET` | `/api/videos/{jobId}` | — |
| Upload video | `POST` | `/api/videos/upload` | `file` (mp4), `team_id=13` |
| Cancel job | `POST` | `/api/videos/{jobId}/cancel` | — |
| Run mapping | `POST` | `/api/videos/{jobId}/player_mapping/auto` | `?team_id=13` |
| Extract reel | `POST` | `/api/videos/{jobId}/highlights/extract` | `?player_id=39&source=annotated` |
| Compose reel | `POST` | `/api/videos/{jobId}/highlights/{reelId}/compose` | — |
| Download reel | `GET` | `/api/videos/{jobId}/highlights/{reelId}/compose/{composedId}/download` | streaming |
| Create export | `POST` | `/api/videos/{jobId}/exports/annotated` | — |
| Get export | `GET` | `/api/videos/{jobId}/exports/annotated/{exportId}` | — |
| Download export | `GET` | `/api/videos/{jobId}/exports/annotated/{exportId}/download` | streaming |

## 7. Known Working Job IDs (for testing without uploading)

These jobs already exist in the database and can be used immediately:

| Job ID | Video | Status | Notes |
|---|---|---|---|
| 22 | bremenvstriton15.mp4 | completed | All remediation flags active. 30/63 tracks mapped. |
| 18 | (previous game) | completed | Older job, some flags not active |

**Composed reels already generated for job 22:**
- Raylon Moats #22: `GET /api/videos/22/highlights/12/compose/21/download`
- Colton Large #10: `GET /api/videos/22/highlights/13/compose/22/download`
- Preston Brookins #23: `GET /api/videos/22/highlights/14/compose/23/download`

Use these URLs to test ExoPlayer playback before building the full generation flow.

---

*This guide was generated for Claude Code running inside Android Studio.*
*Backend: HoopStar.ai FastAPI service — all endpoints tested and verified.*
*Last updated: 2026-06-21*
