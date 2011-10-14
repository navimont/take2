/*
*  Javascript to run the live updates for the map
*
*  Stefan Wehner (2011)
*/
var georequest = new XMLHttpRequest();
var geosprinkle = new XMLHttpRequest();

var layer_geocontacts;
var layer_geosprinkle;
var map;

function setCookie (name, value, seconds) {
  if (typeof(seconds) != 'undefined') {
    var date = new Date();
    date.setTime(date.getTime() + (seconds*1000));
    var expires = "; expires=" + date.toGMTString();
  }
  else {
    var expires = "";
  }

  document.cookie = name+"="+escape(value)+expires+"; path=/";
}

function getCookie (name) {
  name = name + "=";
  var carray = document.cookie.split(';');

  for(var i=0;i < carray.length;i++) {
    var c = carray[i];
    while (c.charAt(0)==' ') c = c.substring(1,c.length);
    if (c.indexOf(name) == 0) return unescape(c.substring(name.length,c.length));
  }

  return null;
}

// zoom map directly to a contact if clicked
function zoomToContact(lat,lon,zoom) {
    if (!document.getElementById('map-full')) {
        t2map_setup(lat,lon,zoom);
    } else {
        map.setView(new L.LatLng(lat, lon), zoom);
    }
}


// callback for data lookup on server
function t2map_sprinkle_reply() {
    if (geosprinkle.readyState == 4) {
        if (geosprinkle.status == 200) {
            var feature_collection = JSON.parse(geosprinkle.responseText);
            // update marker layer
            layer_geosprinkle.addGeoJSON(feature_collection);
        }
    }
}


// callback for search result lookup on server
function t2map_contact_reply() {
    if (georequest.readyState == 4) {
        if (georequest.status == 200) {
            var feature_collection = JSON.parse(georequest.responseText);
            var displayed_features = {'type': 'FeatureCollection', 'features': new Array()};
            var features = feature_collection['features'];
            var valid_coordinates = false;
            if (features.length > 0) {
                var names = "";
                // find the name in the parsed GeoJSON text
                for (var ix = 0; ix < features.length; ix++) {
                    var properties = features[ix]['properties'];
                    if (features[ix]['id'] == 'display') {
                        valid_coordinates = true;
                        // display only features with valid coordinates
                        displayed_features['features'].push(features[ix]);
                        var lat = features[ix]['geometry']['coordinates'][1];
                        var lon = features[ix]['geometry']['coordinates'][0];
                        var zoom = properties['zoom'];
                        // construct the link
                        names = names+"<a href=\"javascript:void(0)\" title=\"zoom to person\" onClick=\"zoomToContact("+lat+","+lon+","+zoom+")\">"+"<img class=\"result_marker\" src=\"/static/leaflet/images/marker.png\">"+"</a>";
                    }
                    names = names+"<div class=\"result_text\">";
                    if ('key' in properties) {
                        names = names+"<p><a href=\"/editcontact?key="+properties['key']+"\" title=\"edit user data\" >"+properties['name']+" "+properties['lastname']+"</a>";
                    } else {
                        names = names+"<p>"+properties['name']+" "+properties['lastname']+"</p>";
                    }
                    names = names+"<p><small>"+properties['place']+"</small></p>";
                    names = names+"</div>";
                }
                // store list of names in a cookie
                setCookie("results", names, 300);
                document.getElementById('results').innerHTML = names;
                // update marker layer
                layer_geocontacts.addGeoJSON(displayed_features);
                if (valid_coordinates) {
                    // update map to show the new bounding box
                    bbox = feature_collection['bbox'];
                    // bbox is minlon,minlat,maxlon,maxlat
                    bounds = new L.LatLngBounds(new L.LatLng(bbox[1],bbox[0]), new L.LatLng(bbox[3],bbox[2]));
                    if (!document.getElementById('map-full')) {
                        t2map_setup(bbox[1],bbox[0],9);
                    }
                    map.fitBounds(bounds);
                }
            } else {
                document.getElementById('results').innerHTML = "<p>Nothing found.<p><p>Do you want to <a href=\"/new?instance=Person,Email,Mobile,Address\">add</a> a new contact?</p>";
            }
        }
    }
}

// looks up names in take2 database which match the string in searchbox
function t2map_contact_req() {
    // get text from input field
    var query = document.getElementById('searchinput').value;
    var url = "/mapdata?query="+query;
    georequest.open("GET", url, true);
    georequest.onreadystatechange = t2map_contact_reply;
    georequest.send(null);
}

// bound to onkeypress event in search box
function send_on_return(event) {
    if (event.keyCode == 13) {
        t2map_contact_req();
    }
}


// looks up all data in the current map viewport
function t2map_sprinkle_req() {
    var bounds = map.getBounds();
    var url = "/mappopulate?bbox="+bounds.getSouthWest().lng+","+bounds.getSouthWest().lat+","+bounds.getNorthEast().lng+","+bounds.getNorthEast().lat;
    geosprinkle.open("GET", url, true);
    geosprinkle.onreadystatechange = t2map_sprinkle_reply;
    geosprinkle.send(null);
}


var t2map_map_move_timeout;
// as the function above, this one delays the map-moved events a little
function t2map_delayed_move(e) {
    // clear existing timeout (if exists)
    clearTimeout(t2map_map_move_timeout);
    // set new timeout
    t2map_map_move_timeout = setTimeout("t2map_sprinkle_req();", 400);
}


function t2map_setup(lat,lon,zoom)
{
    if (!document.getElementById('map-full')) {
        var contentDiv = document.getElementById('content');
        if (!!content) {
            // remove content div
            document.body.removeChild(contentDiv);
        }
        // add map div
        var mapDiv = document.createElement("div");
        mapDiv.id = "map-full";
        document.body.appendChild(mapDiv);
    }
    map = new L.Map('map-full');
    var cloudmadeUrl = 'http://{s}.tile.cloudmade.com/469e39eb2d01411b9f2576eb809346dd/997/256/{z}/{x}/{y}.png',
    cloudmadeAttrib = 'Map data &copy; 2011 OpenStreetMap contributors, Imagery &copy; 2011 CloudMade',
    cloudmade = new L.TileLayer(cloudmadeUrl, {maxZoom: 18, attribution: cloudmadeAttrib});
    map.setView(new L.LatLng(lat, lon), zoom);
    map.addLayer(cloudmade);
    // layer is created before!
    map.addLayer(layer_geocontacts);
    // add layer for non-searched users in the area (sprinkle)
		var PinkIcon = L.Icon.extend({
			iconUrl: '/static/leaflet/images/pink.png',
			shadowUrl: null,
			iconSize: new L.Point(32, 37),
			shadowSize: null,
			iconAnchor: new L.Point(14, 37),
			popupAnchor: new L.Point(2, -32)
		});
    var options = {
		    pointToLayer: function (latlng) {
		        return new L.Marker(latlng, {
		            icon: new PinkIcon()
		        });
		    }
    }
    layer_geosprinkle = new L.GeoJSON(null,options);
    layer_geosprinkle.on("featureparse", function (e) {
        var popupContent = e.properties.popupContent;
        e.layer.bindPopup(popupContent);
    });
    map.addLayer(layer_geosprinkle);
    // add events for the map to trigger loading people's locations
    map.on('drag', t2map_delayed_move);
    t2map_sprinkle_req();
}


function t2map_run() {
    // read last search results from cookie
    var results = getCookie("results");
    if (results) {
        document.getElementById('results').innerHTML = results;
    }
    // create layer for contacts (search results) despite that we may not have a map at first
    layer_geocontacts = new L.GeoJSON();
    // add popups when content is loaded
    layer_geocontacts.on("featureparse", function (e) {
        var popupContent = e.properties.popupContent;
        e.layer.bindPopup(popupContent);
    });
    // only for page with map
    if (!!document.getElementById('map-full')) {
        // coordinates should be submitted by the application
        lat = parseFloat(document.getElementById('login_user_lat').value)
        lon = parseFloat(document.getElementById('login_user_lon').value)
        t2map_setup(lat,lon,12);
    }
}

function post_to_url(path, params, method) {
    method = method || "get";

    var form = document.createElement("form");
    form.setAttribute("method", method);
    form.setAttribute("action", path);

    for(var key in params) {
        var hiddenField = document.createElement("input");
        hiddenField.setAttribute("type", "hidden");
        hiddenField.setAttribute("name", key);
        hiddenField.setAttribute("value", params[key]);

        form.appendChild(hiddenField);
    }

    document.body.appendChild(form);
    form.submit();
}
