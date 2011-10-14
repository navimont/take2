var georequest = new XMLHttpRequest();
var geocoder;
var latlon;

function geocoder_cb(results, status) {
    var place = "";
    if (status == google.maps.GeocoderStatus.OK) {
          // get data for administrative zoom: country, state, region, town
          var place = "";
          for (var ix in results[0].address_components) {
              var admin = results[0].address_components[ix];
              if (admin.types.indexOf("neighborhood") != -1
                  || admin.types.indexOf("sublocality") != -1
                  || admin.types.indexOf("locality") != -1 ) {
                  place = place+admin.long_name+", ";
              }
          }
          // remove last comma
          place = place.replace(/,\s+$/,"");
    }

  // present location in header
  document.getElementById("login_user_place").innerHTML =("<h4>"+place+"</h4>");
  // send location to server
  var user = document.getElementById("login_user_key").value;
  var url = "/location?user="+user+"&lat="+latlon.lat()+"&lon="+latlon.lng()+"&place="+place;
  georequest.open("GET", url, true);
  // we are not interested in any reply
  georequest.send(null);
}

// geolocation.getCurrentPosition error callback
function position_error_cb (err) {
    var user = document.getElementById("login_user_key").value;
    var url = "/location?user="+user+"&err="+err.code;
    georequest.open("GET", url, true);
    // we are not interested in any reply
    georequest.send(null);
}

// geolocation.getCurrentPosition position callback
function position_cb (position) {
    // geoencode position
    latlon = new google.maps.LatLng(position.coords.latitude, position.coords.longitude);
    geocoder.geocode( { 'location': latlon }, geocoder_cb);
}

/* initialize geocoder, is called back by loadMapScript */
function initializeGeocoder() {
    geocoder = new google.maps.Geocoder();
    // maximumAge in milliseconds
    navigator.geolocation.getCurrentPosition(position_cb, position_error_cb, {timeout: 10000, maximumAge: 300000});
}


function loadMapScript() {
    var script_loaded = document.getElementById("google_map_script");
    if (!script_loaded) {
        var script = document.createElement("script");
        script.id = "google_map_script";
        script.type = "text/javascript";
        script.src = "http://maps.googleapis.com/maps/api/js?sensor=false&callback=initializeGeocoder";
        document.body.appendChild(script);
    };
}

function t2_geolocator_run() {
    ask_geolocation = document.getElementById("geolocation_request").value;
    if (ask_geolocation == "True") {
        // start the chain of call backs only if we can actually retrieve position
        if (!navigator.geolocation) {
            return;
        }
        // contains functionality for geolocation
        loadMapScript();
    }
}
