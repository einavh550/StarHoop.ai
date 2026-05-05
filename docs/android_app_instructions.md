# HoopStar.ai — Android App Development Instructions

Purpose
-------
This document is the developer handoff for the Android app milestone. It describes what the app should do, how it should look, how it should connect to the backend, and what a top-grade implementation should include. Your friend should be able to use this as the starting point for building the app in Android Studio using Kotlin.

Product Vision
--------------
Build a polished Android companion app for HoopStar.ai that helps a user browse processed basketball video jobs, inspect detections, trigger backend actions, and watch annotated exports. The app is not doing the CV work locally; it is a client for the backend pipeline that already exists in the other milestones.

Core idea
---------
The backend already handles:
- video upload and processing
- detection tracking
- jersey OCR
- player mapping
- action recognition
- annotated export generation

The Android app should expose that work in a clean mobile interface and make it easy to:
- see which jobs are completed or still processing
- inspect players and jersey mappings
- review OCR debug information when something looks wrong
- generate and watch an annotated MP4
- share or download the output video

Design goals
------------
This should feel like a serious production app, not a demo.

The app should be:
- modern
- fast
- intuitive
- minimal but premium
- easy to navigate with one hand
- consistent in typography, spacing, and color use
- reliable for long-running server tasks

Recommended Android stack
-------------------------
Use:
- Kotlin
- Jetpack Compose
- MVVM architecture
- Coroutines and Flow
- Retrofit + OkHttp
- Hilt for dependency injection
- ExoPlayer for video playback
- Coil for images and thumbnails
- Room only if local caching becomes necessary
- EncryptedSharedPreferences for tokens
- Kotlinx Serialization or Moshi for JSON

Suggested minimum SDK
---------------------
- Min SDK: 24 or higher
- Target SDK: latest stable available in Android Studio

Information architecture
------------------------
The app should have the following main sections:

1. Login / API Setup
- Enter backend URL
- Enter API token or login credentials if authentication is added later
- Save credentials securely
- Validate connection before entering the app

2. Jobs Dashboard
- Show all processed or processing video jobs
- Each item should show:
  - job id
  - team name or team id
  - status
  - progress
  - source filename
  - created time
- The dashboard should support refresh, search, and basic filters

3. Job Detail Screen
- Show job summary
- Show progress and backend status
- Show available actions:
  - recompute mapping
  - create annotated export
  - check OCR debug output
  - download latest annotated export
- Show recent exports and their statuses

4. Video Viewer Screen
- Play the annotated export
- Show playback controls
- Optionally overlay detection boxes and labels on top of the video
- Allow download and share of the MP4

5. Frame Inspector / OCR Debug Screen
- Inspect a frame and a track
- Show crop preview
- Show OCR text blocks
- Show candidate jersey numbers and confidence
- Show whether a candidate was accepted or rejected

6. Settings Screen
- Backend URL
- Token management
- Cache controls
- Debug flags
- Logout

Visual style guidance
---------------------
The UI should look premium and intentional.

Recommended style:
- dark or neutral theme with strong contrast
- large readable typography
- clear hierarchy between dashboard, detail, and viewer screens
- card-based job list with subtle elevation
- stable spacing and alignment
- one accent color used consistently for status and primary actions
- avoid cluttered controls

Suggested layout behavior:
- top app bar with app title and refresh action
- dashboard cards with colored status pill
- sticky action area on detail screen
- bottom sheet or tab switcher for export details and OCR debug view
- full-screen player with overlay toggle

User experience principles
--------------------------
- Make long operations visible with progress indicators
- Use retries and clear error states
- Never hide backend failures
- Keep destructive actions behind confirmation dialogs
- Show empty states that explain what the user should do next
- Preserve state when the user returns from the video player

Backend integration overview
----------------------------
The Android app should call the existing FastAPI backend over HTTPS using REST APIs.

Important backend endpoints to support:
- GET /api/videos
- GET /api/videos/{job_id}
- POST /api/videos/{job_id}/player_mapping/auto?team_id={team_id}&recompute_from_frames=true
- POST /api/videos/{job_id}/exports/annotated
- GET /api/videos/{job_id}/exports/annotated/{export_id}
- GET /api/videos/{job_id}/exports/annotated/{export_id}/download
- GET /api/videos/{job_id}/ocr/debug/analyze?frame_number={frame_number}&track_id={track_id}

How the connection should work
------------------------------
- Use Retrofit interfaces for all backend calls
- Use a shared OkHttp client
- Add authorization headers through an interceptor
- Use suspend functions for network calls
- Use @Streaming for downloading MP4 files
- Poll status endpoints for long-running jobs
- Treat the backend as the source of truth

Suggested DTOs
--------------
The app should define DTOs for at least:
- VideoJob
- AnnotatedVideoExport
- VideoJobStatusResponse
- AnnotatedVideoExportStatusResponse
- OCRDebugAnalysisResponse
- TextBlock
- Candidate

Example Kotlin shape:
```kotlin
@Serializable
data class VideoJobDto(
    val job_id: Int,
    val team_id: Int,
    val status: String,
    val source_filename: String,
    val total_frames: Int? = null,
    val processed_frames: Int? = null,
    val error_message: String? = null
)
```

Playback and overlay rules
--------------------------
- Use ExoPlayer for the MP4 export
- Allow the user to toggle overlays on and off
- If overlays are enabled, draw bounding boxes and labels over the video surface
- If overlay data is not available locally, fetch it from the backend or rely on the annotated export video
- Keep the video experience smooth and avoid blocking the UI thread

OCR debug behavior
------------------
The app should expose OCR debug information because this project depends heavily on visual QA.

The debug screen should show:
- original crop or preprocessed crop
- OCR text blocks returned by the backend
- parsed jersey candidates
- confidence values
- whether the backend accepted or rejected the candidate
- the existing jersey number if one was already stored

Security requirements
---------------------
- Never hardcode secrets
- Store tokens in encrypted storage
- Use HTTPS only
- Avoid logging tokens or sensitive payloads

Performance requirements
------------------------
- Cache thumbnails
- Cache export metadata if needed
- Stream large MP4 files instead of loading them fully into memory
- Keep list screens responsive with paging or lazy loading

Testing requirements
--------------------
The app should include:
- ViewModel unit tests
- Retrofit / repository tests with MockWebServer
- UI tests for main navigation flows
- Basic video playback smoke testing

Definition of done
------------------
The milestone should be considered complete when the app can:
- connect to the backend
- list jobs
- open a job detail page
- trigger recompute
- create an annotated export
- download the export
- play the export in the app
- show OCR debug output for a frame and track

Implementation priorities
-------------------------
1. Build the app shell and navigation
2. Add backend connection and auth
3. Add jobs dashboard and job detail screens
4. Add export creation and download flow
5. Add video player and overlay support
6. Add OCR debug screen
7. Add tests and polish

Expected file structure
-----------------------
A clean starter project should roughly look like this:
- app/
  - src/main/java/.../ui
  - src/main/java/.../data
  - src/main/java/.../network
  - src/main/java/.../viewmodel
  - src/main/java/.../player
  - src/main/res
- README.md
- build.gradle.kts
- settings.gradle.kts

Handoff notes for the developer
-------------------------------
- Ask for sample JSON if any backend field is unclear
- Build the UI against the real backend contract, not guessed data
- Prefer clean architecture and keep business logic out of composables
- Make the app feel like a product, not a prototype
- Focus on clarity, stability, and a good review workflow

This file is intended to be the single source of truth for the Android app milestone.
