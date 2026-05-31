import {Config} from '@remotion/cli/config';

// Canonical render policy for the CLI / Studio / bundle. These match the flags
// in scripts/remotion_render.sh so `npm run render`, `render:run`, and the local
// path all agree. NOTE: @remotion/lambda render reads its options from the CLI
// flags in scripts/lambda_render.sh, NOT from this file — keep the two in sync.
// The OpenGL renderer is intentionally left at the default: changing it churns
// pixel output (and the SHA-based artifact identity) for no quality gain here.
Config.setCodec('h264');
Config.setPixelFormat('yuv420p');
Config.setCrf(18);
Config.setAudioCodec('aac');

Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(95);
Config.setOverwriteOutput(true);
