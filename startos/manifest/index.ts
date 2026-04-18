import { setupManifest } from '@start9labs/start-sdk'
import { short, long } from './i18n'

export const manifest = setupManifest({
  id: 'hashbidder9',
  title: 'Hashbidder9',
  license: 'MIT',
  packageRepo: 'https://github.com/counterweightoperator/hashbidder',
  upstreamRepo: 'https://github.com/counterweightoperator/hashbidder',
  marketingUrl: 'https://github.com/counterweightoperator/hashbidder',
  donationUrl: null,
  docsUrls: [],
  description: { short, long },
  volumes: ['main'],
  images: {
    main: {
      source: {
        dockerBuild: {
          dockerfile: './Dockerfile',
          workdir: '.',
        },
      },
    },
  },
  alerts: {
    install: null,
    update: null,
    uninstall: null,
    restore: null,
    start: null,
    stop: null,
  },
  dependencies: {},
})
