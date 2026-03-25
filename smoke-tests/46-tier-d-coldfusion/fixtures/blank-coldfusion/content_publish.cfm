<!---
================================================================
FILE:        content_publish.cfm
DESCRIPTION: CMS content publishing pipeline (ColdFusion / CFML)
             Publishes updated content to the e-commerce CMS:
             - Reads content record from SQL Server (CMS DB)
             - Updates publish status and version
             - Flushes application cache regions
             - Purges CDN edge caches (CloudFront)
             - Syncs product search index (Elasticsearch)

APP SERVER:  Adobe ColdFusion 2023 / Lucee 6
DATABASE:    Microsoft SQL Server 2019 — ContentDB
CDN:         Amazon CloudFront
SEARCH:      Elasticsearch 8.x
================================================================
--->
<cfsilent>
<cfparam name="form.page_id"      default="">
<cfparam name="form.content_type" default="">
<cfparam name="form.author"       default="">
<cfparam name="form.body_html"    default="">
<cfparam name="form.product_ids"  default="">

<!--- Only process on POST --->
<cfset result = {
    success   : false,
    version_id: "",
    message   : ""
}>

<cfif CGI.REQUEST_METHOD EQ "POST" AND LEN(TRIM(form.page_id))>

    <!--- ============================================================
          Step 1: Connect to CMS database
          ============================================================ --->
    <cftry>
        <cfquery name="qGetContent" datasource="ContentDB" result="qResult">
            SELECT  content_id, title, page_type, publish_status,
                    version_no, updated_by, updated_dt
            FROM    cms_content
            WHERE   page_id = <cfqueryparam value="#TRIM(form.page_id)#"
                                            cfsqltype="cf_sql_varchar">
        </cfquery>

        <cfcatch type="database">
            <cfset result.message = "DB read failed: " & cfcatch.message>
            <cfrethrow>
        </cfcatch>
    </cftry>

    <cfif qGetContent.RecordCount EQ 0>
        <cfset result.message = "Content not found: #form.page_id#">
    <cfelse>

        <!--- ============================================================
              Step 2: Update publish status + increment version
              ============================================================ --->
        <cfset newVersion = qGetContent.version_no + 1>
        <cfset versionID  = CreateUUID()>

        <cftry>
            <cfquery datasource="ContentDB">
                UPDATE  cms_content
                SET     publish_status = 'PUBLISHED',
                        version_no     = <cfqueryparam value="#newVersion#"
                                                       cfsqltype="cf_sql_integer">,
                        version_uuid   = <cfqueryparam value="#versionID#"
                                                       cfsqltype="cf_sql_varchar">,
                        published_by   = <cfqueryparam value="#TRIM(form.author)#"
                                                       cfsqltype="cf_sql_varchar">,
                        published_dt   = GETDATE()
                WHERE   page_id = <cfqueryparam value="#TRIM(form.page_id)#"
                                               cfsqltype="cf_sql_varchar">
            </cfquery>
            <cfcatch type="database">
                <cfset result.message = "DB update failed: " & cfcatch.message>
                <cfrethrow>
            </cfcatch>
        </cftry>

        <!--- ============================================================
              Step 3: Flush ColdFusion application cache
              ============================================================ --->
        <cftry>
            <cfset cacheRegion = "content_" & LCASE(TRIM(form.content_type))>
            <cfcache action="flush" region="#cacheRegion#">
            <cfset result.cache_flushed = true>
            <cfcatch type="any">
                <!--- Non-fatal: log and continue --->
                <cflog file="cms_publish" type="warning"
                       text="Cache flush failed for #cacheRegion#: #cfcatch.message#">
            </cfcatch>
        </cftry>

        <!--- ============================================================
              Step 4: Purge CDN (CloudFront) if images present
              ============================================================ --->
        <cfset imageCount = 0>
        <cfif LISTLEN(form.product_ids) GT 0>
            <!--- Build list of image paths to purge --->
            <cfset purgePathList = "/images/content/#TRIM(form.page_id)#/*">

            <cftry>
                <cfhttp method="POST"
                        url="https://cloudfront-api.internal/purge"
                        result="httpResult"
                        timeout="10">
                    <cfhttpparam type="header" name="Content-Type"
                                 value="application/json">
                    <cfhttpparam type="body"
                                 value='{"distribution":"E1ABCXYZ123","paths":["#purgePathList#"]}'>
                </cfhttp>
                <cfset imageCount = 1>
            <cfcatch type="any">
                <cflog file="cms_publish" type="warning"
                       text="CDN purge failed: #cfcatch.message#">
            </cfcatch>
        </cftry>
        </cfif>

        <!--- ============================================================
              Step 5: Sync search index (Elasticsearch)
              ============================================================ --->
        <cfset productCount = LISTLEN(form.product_ids)>
        <cfif productCount GT 0>
            <cfset esPayload = SerializeJSON({
                "index" : "products-v3",
                "page_id" : TRIM(form.page_id),
                "product_ids" : ListToArray(form.product_ids),
                "version_uuid" : versionID,
                "action" : "reindex"
            })>

            <cftry>
                <cfhttp method="POST"
                        url="http://es-cluster.internal:9200/_bulk_reindex"
                        result="esResult"
                        timeout="15">
                    <cfhttpparam type="header" name="Content-Type"
                                 value="application/json">
                    <cfhttpparam type="body" value="#esPayload#">
                </cfhttp>
            <cfcatch type="any">
                <cflog file="cms_publish" type="warning"
                       text="Search sync failed: #cfcatch.message#">
            </cfcatch>
        </cftry>
        </cfif>

        <!--- ============================================================
              Build result
              ============================================================ --->
        <cfset result = {
            success      : true,
            page_id      : TRIM(form.page_id),
            version_id   : versionID,
            version_no   : newVersion,
            content_type : TRIM(form.content_type),
            author       : TRIM(form.author),
            images_purged: imageCount,
            products_indexed: productCount,
            message      : "Published successfully"
        }>

        <!--- Log to ColdFusion application log --->
        <cflog file="cms_publish" type="information"
               text="PUBLISHED page=#result.page_id# v=#newVersion# by=#result.author# uuid=#versionID#">

    </cfif>  <!--- end RecordCount check --->

</cfif>  <!--- end POST check --->
</cfsilent>
<!DOCTYPE html>
<html>
<head><title>CMS Content Publisher</title></head>
<body>
<h1>Content Publish</h1>
<cfif result.success>
  <p style="color:green">Published: <strong>#result.page_id#</strong> v<strong>#result.version_no#</strong></p>
  <p>Version UUID: #result.version_id#</p>
<cfelseif LEN(result.message)>
  <p style="color:red">Error: #result.message#</p>
</cfif>
<form method="POST" action="content_publish.cfm">
  <label>Page ID: <input type="text" name="page_id"/></label><br/>
  <label>Type:
    <select name="content_type">
      <option>category</option>
      <option>product</option>
      <option>promotion</option>
      <option>blog_post</option>
    </select>
  </label><br/>
  <label>Author: <input type="text" name="author"/></label><br/>
  <label>Product IDs (comma-separated): <input type="text" name="product_ids"/></label><br/>
  <input type="submit" value="Publish"/>
</form>
</body>
</html>
