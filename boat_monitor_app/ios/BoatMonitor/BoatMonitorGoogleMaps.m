#import <React/RCTBridgeModule.h>

@interface BoatMonitorGoogleMaps : NSObject <RCTBridgeModule>
@end

@implementation BoatMonitorGoogleMaps

RCT_EXPORT_MODULE();

+ (BOOL)requiresMainQueueSetup
{
  return NO;
}

/// True when the built app has GMSApiKey in Info.plist (configure-google-maps-ios.sh on EAS).
/// AppDelegate calls GMSServices with the same key at launch before any MapView mounts.
RCT_EXPORT_BLOCKING_SYNCHRONOUS_METHOD(isReady)
{
  NSString *mapsKey = [[NSBundle mainBundle] objectForInfoDictionaryKey:@"GMSApiKey"];
  BOOL ready = mapsKey != nil && mapsKey.length > 0;
  return @(ready);
}

@end
