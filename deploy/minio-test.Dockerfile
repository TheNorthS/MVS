# 独立集成测试使用；固定上游源码，不依赖已不可匿名拉取的MinIO镜像仓库。
# 上游RELEASE.2025-10-15T17-29-55Z，AGPL-3.0；不包含在MVS的PyPI包中。
FROM golang:1.24.8 AS build
RUN CGO_ENABLED=0 go install -trimpath github.com/minio/minio@9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a \
    && cp /go/pkg/mod/github.com/minio/minio@*/LICENSE /minio-LICENSE

FROM alpine:3.22
COPY --from=build /go/bin/minio /usr/local/bin/minio
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build /minio-LICENSE /usr/share/licenses/minio/LICENSE
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision="9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data"]
