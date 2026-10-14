/**
 * Runtime fingerprint for EAS Update (app.json runtimeVersion policy "fingerprint").
 * Every push bumps the app version (CLAUDE.md); leaving it out of the fingerprint keeps
 * installed builds receiving JS updates until a native change actually needs a new build.
 * @type {import('@expo/fingerprint').Config}
 */
module.exports = {
  sourceSkips: ['ExpoConfigVersions'],
};
